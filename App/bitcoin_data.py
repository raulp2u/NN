"""Baixa arquivos primários BTCUSDT 1m e produz janelas de 30 minutos em CSV."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from zipfile import ZipFile

BASE = "https://data.binance.vision/"
CATALOG = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DOCS = "https://github.com/binance/binance-public-data"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
MINUTE = 60_000
WINDOW = 30 * MINUTE
FIELDS = ("open", "high", "low", "close", "volume")


def fetch(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": "QuantLab-data-research/1.0"}), timeout=60) as source:
                return source.read()
        except OSError:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def catalog(prefix):
    result, marker = [], None
    while True:
        query = {"prefix": prefix, "max-keys": "1000"}
        if marker:
            query["marker"] = marker
        root = ET.fromstring(fetch(CATALOG + "?" + urlencode(query)))
        for item in root.findall("s:Contents", NS):
            key = item.findtext("s:Key", namespaces=NS)
            if key.endswith(".zip"):
                result.append({"key": key, "size": int(item.findtext("s:Size", namespaces=NS))})
        if root.findtext("s:IsTruncated", namespaces=NS) != "true":
            return result
        marker = root.findtext("s:NextMarker", namespaces=NS)
        if not marker:
            contents = root.findall("s:Contents", NS)
            if not contents:
                raise ValueError("Catálogo truncado sem marcador")
            marker = contents[-1].findtext("s:Key", namespaces=NS)


def select_files(as_of):
    monthly = catalog("data/spot/monthly/klines/BTCUSDT/1m/")
    chosen, covered = [], set()
    for item in monthly:
        period = Path(item["key"]).name.removeprefix("BTCUSDT-1m-").removesuffix(".zip")
        start = date.fromisoformat(period + "-01")
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        if end <= as_of:
            chosen.append(item)
            covered.add(period)
    if not chosen:
        raise ValueError("Nenhum arquivo mensal completo disponível")
    # Complementa meses ainda sem arquivo mensal; nunca usa o dia corrente.
    first_daily = max(date.fromisoformat(p + "-01") for p in covered)
    first_daily = (first_daily.replace(day=28) + timedelta(days=4)).replace(day=1)
    month = first_daily
    while month <= as_of:
        for item in catalog(f"data/spot/daily/klines/BTCUSDT/1m/BTCUSDT-1m-{month:%Y-%m}-"):
            day = date.fromisoformat(Path(item["key"]).name.removeprefix("BTCUSDT-1m-").removesuffix(".zip"))
            if day < as_of and day.strftime("%Y-%m") not in covered:
                chosen.append(item)
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return sorted(chosen, key=lambda item: Path(item["key"]).name)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_hash(path, expected):
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"Checksum divergente: {path.name}; esperado {expected}, obtido {actual}")
    return actual


def download(item, raw):
    url = BASE + item["key"]
    checksum = fetch(url + ".CHECKSUM").decode("ascii")
    parts = checksum.split()
    if len(parts) != 2 or parts[1].lstrip("*") != Path(item["key"]).name:
        raise ValueError(f"Formato de checksum inesperado: {url}")
    expected = parts[0].lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise ValueError("Hash SHA-256 inválido")
    local = raw / Path(item["key"]).name
    if not local.exists():
        temporary = local.with_suffix(".zip.part")
        temporary.write_bytes(fetch(url))
        verify_hash(temporary, expected)
        temporary.replace(local)
    actual = verify_hash(local, expected)
    if local.stat().st_size != item["size"]:
        raise ValueError(f"Tamanho divergente do catálogo: {local.name}")
    (raw / (local.name + ".CHECKSUM")).write_text(checksum, encoding="ascii")
    return {**item, "url": url, "checksum_url": url + ".CHECKSUM", "sha256": actual,
            "local": str(local.resolve()), "verified_utc": datetime.now(timezone.utc).isoformat()}


def timestamp_ms(value):
    integer = int(value)
    # Os arquivos spot mudam de ms para us em janeiro de 2025.
    return integer // 1000 if integer >= 100_000_000_000_000 else integer


def parse_row(row):
    if len(row) != 12:
        raise ValueError(f"Esperadas 12 colunas Binance; recebidas {len(row)}")
    timestamp = timestamp_ms(row[0])
    original = int(row[0])
    unit = 1000 if original >= 100_000_000_000_000 else 1
    if original % (MINUTE * unit):
        raise ValueError("Abertura desalinhada da grade de um minuto")
    if int(row[6]) != original + MINUTE * unit - 1:
        raise ValueError("Fechamento incompatível com candle de um minuto")
    values = tuple(float(value) for value in row[1:6])
    if not all(math.isfinite(x) for x in values):
        raise ValueError("OHLCV contém valor não finito")
    o, h, low, c, v = values
    if min(o, h, low, c) <= 0 or v < 0 or not low <= min(o, c) <= max(o, c) <= h:
        raise ValueError("OHLCV inválido")
    return timestamp, tuple(row[1:6])


def utc(timestamp):
    return datetime.fromtimestamp(timestamp // 1000, timezone.utc).isoformat().replace("+00:00", "Z")


class Windows:
    def __init__(self):
        self.bucket = None
        self.rows = []
        self.complete = 0
        self.incomplete = 0

    def push(self, timestamp, values):
        bucket = timestamp // WINDOW
        if bucket != self.bucket:
            self.finish()
            self.bucket, self.rows = bucket, []
        self.rows.append((timestamp, values))
        if len(self.rows) == 30 and self.rows[0][0] % WINDOW == 0:
            if all(self.rows[i][0] - self.rows[i - 1][0] == MINUTE for i in range(1, 30)):
                self.complete += 1
                return self.rows
        return None

    def finish(self):
        if self.rows and not (len(self.rows) == 30 and self.rows[0][0] % WINDOW == 0
                             and self.rows[-1][0] - self.rows[0][0] == 29 * MINUTE):
            self.incomplete += 1


def build(output, files, as_of):
    normalized_part = output / "btc_usdt_1m.csv.part"
    snapshots_part = output / "snapshots_30m.csv.part"
    quarantine_part = output / "quarantine.csv.part"
    cutoff = int(datetime.combine(as_of, datetime.min.time(), timezone.utc).timestamp()) * 1000
    gaps, previous, first, total = [], None, None, 0
    raw_count = invalid_count = 0
    windows = Windows()
    with normalized_part.open("w", encoding="utf-8", newline="") as normalized, snapshots_part.open("w", encoding="utf-8", newline="") as snapshots, quarantine_part.open("w", encoding="utf-8", newline="") as rejected:
        writer = csv.writer(normalized)
        writer.writerow(["timestamp", *FIELDS])
        quarantine = csv.writer(rejected)
        quarantine.writerow(["source_file", "line", "reason", "raw_row_json"])
        snap = csv.writer(snapshots)
        snap.writerow(["window_id", "start_utc", "available_at_utc", "samples"] +
                      [f"{field}_{i:02}" for i in range(30) for field in FIELDS])
        for number, source in enumerate(files, 1):
            count = 0
            file_rejected = 0
            with ZipFile(source["local"]) as archive:
                entries = archive.namelist()
                if entries != [Path(source["local"]).with_suffix(".csv").name]:
                    raise ValueError(f"Conteúdo ZIP inesperado: {source['local']}")
                with archive.open(entries[0]) as stream:
                    for line, row in enumerate(csv.reader(io.TextIOWrapper(stream, encoding="utf-8-sig")), 1):
                        raw_count += 1
                        try:
                            timestamp, values = parse_row(row)
                        except (ValueError, OverflowError) as error:
                            quarantine.writerow([entries[0], line, str(error), json.dumps(row)])
                            invalid_count += 1
                            file_rejected += 1
                            continue
                        if timestamp + MINUTE > cutoff:
                            raise ValueError("Fonte contém candle além do corte solicitado")
                        if previous is not None:
                            if timestamp <= previous:
                                raise ValueError(f"Duplicata ou inversão em {utc(timestamp)}")
                            if timestamp - previous != MINUTE:
                                gaps.append({"after_utc": utc(previous), "next_utc": utc(timestamp),
                                             "missing_minutes": (timestamp - previous) // MINUTE - 1})
                        first = timestamp if first is None else first
                        previous = timestamp
                        total += 1
                        count += 1
                        writer.writerow([utc(timestamp), *values])
                        window = windows.push(timestamp, values)
                        if window:
                            snap.writerow([windows.complete - 1, utc(window[0][0]), utc(timestamp + MINUTE), 30,
                                           *(value for _, sample in window for value in sample)])
            if not count:
                raise ValueError(f"Arquivo sem candles: {source['local']}")
            source["candles"] = count
            source["quarantined_rows"] = file_rejected
            if number % 10 == 0 or number == len(files):
                print(f"Conversão: {number}/{len(files)} arquivos; {total:,} candles; {windows.complete:,} janelas", flush=True)
    windows.finish()
    if not windows.complete:
        raise ValueError("Nenhuma janela completa")
    splits_part = output / "splits.csv.part"
    counts = {"train": 0, "validation": 0, "test": 0}
    boundaries = {}
    train_end = windows.complete * 8 // 10
    validation_end = windows.complete * 9 // 10
    with snapshots_part.open(encoding="utf-8", newline="") as source, splits_part.open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(["window_id", "start_utc", "available_at_utc", "split"])
        for row in csv.DictReader(source):
            index = int(row["window_id"])
            split = "train" if index < train_end else "validation" if index < validation_end else "test"
            writer.writerow([index, row["start_utc"], row["available_at_utc"], split])
            counts[split] += 1
            boundaries.setdefault(split, {"first_start_utc": row["start_utc"]})["last_available_at_utc"] = row["available_at_utc"]
    products = []
    for temporary in (normalized_part, snapshots_part, splits_part, quarantine_part):
        final = temporary.with_suffix("")
        temporary.replace(final)
        products.append({"path": final.name, "bytes": final.stat().st_size, "sha256": sha256(final)})
    return {"raw_rows": raw_count, "quarantined_rows": invalid_count,
            "candles": total, "first_open_utc": utc(first), "last_close_exclusive_utc": utc(previous + MINUTE),
            "windows": windows.complete, "incomplete_buckets_excluded": windows.incomplete,
            "candles_not_in_complete_windows": total - windows.complete * 30,
            "gaps": gaps, "gap_count": len(gaps), "missing_minutes": sum(g["missing_minutes"] for g in gaps),
            "splits": counts, "split_boundaries": boundaries, "products": products}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, type=date.fromisoformat,
                        help="Data UTC exclusiva; não inclui este dia")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "data" / "bitcoin")
    args = parser.parse_args()
    if args.as_of > datetime.now(timezone.utc).date():
        parser.error("Corte futuro não permitido")
    args.out.mkdir(parents=True, exist_ok=True)
    if (args.out / "manifest.json").exists():
        parser.error("Dataset concluído já existe. Use outra pasta para preservar a versão anterior.")
    raw = args.out / "raw"
    raw.mkdir(exist_ok=True)
    files = select_files(args.as_of)
    print(f"Catálogo: {len(files)} ZIPs, {sum(item['size'] for item in files):,} bytes", flush=True)
    results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(download, item, raw): item for item in files}
        for index, future in enumerate(as_completed(futures), 1):
            item = future.result()
            results[item["key"]] = item
            if index % 10 == 0 or index == len(files):
                print(f"Download e SHA-256: {index}/{len(files)}", flush=True)
    verified = [results[item["key"]] for item in files]
    # Persiste proveniência mesmo se uma linha inválida interromper a conversão.
    (args.out / "sources.json").write_text(json.dumps(verified, indent=2), encoding="utf-8")
    quality = build(args.out, verified, args.as_of)
    manifest = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
                "as_of_exclusive_utc": args.as_of.isoformat(), "symbol": "BTCUSDT", "market": "Binance spot",
                "price_unit": "USDT", "volume_unit": "BTC", "resolution_seconds": 60,
                "window_minutes": 30, "stride_minutes": 30, "samples_per_window": 30,
                "documentation": DOCS, "sources": verified, "quality": quality,
                "sampling": "Grade UTC fixa, sem seleção de picos/fundos e sem sobreposição",
                "labels": "Nenhum rótulo futuro; somente entradas. Definir alvo antes de treinar.",
                "limitations": ["Uma única bolsa e par, sem histórico anterior à listagem",
                                "OHLCV 1m não preserva sequência intraminuto, spread ou livro de ofertas",
                                "Checksum verifica correspondência ao arquivo publicado, não exatidão econômica",
                                "Divisão 80/10/10 por janelas; purgar fronteiras quando definir rótulos futuros"]}
    temporary = args.out / "manifest.json.part"
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(args.out / "manifest.json")
    print(json.dumps({key: value for key, value in quality.items() if key != "gaps"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
