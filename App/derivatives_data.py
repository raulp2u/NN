"""Derivativos BTCUSDT dos futuros perpétuos USDⓈ-M: funding, open interest e razão de volume taker.

Histórico: Binance Public Data, com checksum SHA-256 de cada arquivo. Ao vivo: API pública fapi,
sem chave. Liquidações ficam de fora: não há série histórica pública contínua.
"""

import argparse
import asyncio
from bisect import bisect_right
import csv
from datetime import date, datetime, timedelta, timezone
import io
import json
import math
from pathlib import Path
import time
from urllib.request import Request, urlopen
from zipfile import ZipFile

from bitcoin_data import catalog, download, sha256

FUNDING_PREFIX = "data/futures/um/monthly/fundingRate/BTCUSDT/"
METRICS_PREFIX = "data/futures/um/daily/metrics/BTCUSDT/"
FUNDING_HEADER = ["calc_time", "funding_interval_hours", "last_funding_rate"]
METRICS_COLUMNS = ("create_time", "sum_open_interest", "sum_taker_long_short_vol_ratio")
FAPI = "https://fapi.binance.com"
LIVE = {"funding": f"{FAPI}/fapi/v1/fundingRate?symbol=BTCUSDT&limit=3",
        "open_interest": f"{FAPI}/futures/data/openInterestHist?symbol=BTCUSDT&period=5m&limit=300",
        "taker": f"{FAPI}/futures/data/takerlongshortRatio?symbol=BTCUSDT&period=5m&limit=300"}
# Registros de 5 minutos: considerados disponíveis só 5 minutos depois do carimbo (hipótese conservadora).
METRICS_DELAY = 300
METRICS_MAX_AGE = 900
FUNDING_MAX_AGE = 9 * 3600
OI_LAGS = (3600, 4 * 3600, 24 * 3600)
FEATURES = ["funding_bps", "funding_age_8h", "oi_change_1h", "oi_change_4h", "oi_change_24h",
            "taker_ratio_log", "has_funding", "has_metrics"]


def select(as_of):
    """Arquivos completos antes da data de corte: funding mensal e métricas diárias."""
    chosen = []
    for item in catalog(FUNDING_PREFIX):
        month = date.fromisoformat(Path(item["key"]).stem.removeprefix("BTCUSDT-fundingRate-") + "-01")
        if (month.replace(day=28) + timedelta(days=4)).replace(day=1) <= as_of:
            chosen.append(("funding", item))
    for item in catalog(METRICS_PREFIX):
        if date.fromisoformat(Path(item["key"]).stem.removeprefix("BTCUSDT-metrics-")) < as_of:
            chosen.append(("metrics", item))
    return sorted(chosen, key=lambda pair: Path(pair[1]["key"]).name)


def _epoch(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())


def parse_funding(lines):
    reader = csv.reader(lines)
    if next(reader, None) != FUNDING_HEADER:
        raise ValueError("Cabeçalho inesperado no arquivo de funding")
    for row in reader:
        moment, rate = int(row[0]) // 1000, float(row[2])
        if not math.isfinite(rate):
            raise ValueError("Funding não finito")
        yield moment, rate


def parse_metrics(lines):
    reader = csv.reader(lines)
    header = next(reader, None) or []
    if any(column not in header for column in METRICS_COLUMNS):
        raise ValueError("Cabeçalho inesperado no arquivo de métricas")
    index = [header.index(column) for column in METRICS_COLUMNS]
    for row in reader:
        moment = _epoch(row[index[0]])
        if not row[index[1]] or not row[index[2]]:
            continue  # campo vazio: lacuna de cobertura, não valor zero
        oi, taker = float(row[index[1]]), float(row[index[2]])
        if not (math.isfinite(oi) and math.isfinite(taker)) or oi <= 0 or taker <= 0:
            continue  # registros vazios ou nulos acontecem; a lacuna vira ausência de cobertura
        yield moment, oi, taker


def read_zip(path, parser):
    with ZipFile(path) as archive:
        entries = archive.namelist()
        if len(entries) != 1 or not entries[0].endswith(".csv"):
            raise ValueError(f"Conteúdo ZIP inesperado: {path}")
        with archive.open(entries[0]) as stream:
            yield from parser(io.TextIOWrapper(stream, encoding="utf-8-sig"))


def build(output, as_of, files=None):
    raw = output / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    files = select(as_of) if files is None else files
    funding, metrics, sources = {}, {}, []
    for kind, item in files:
        source = download(item, raw)
        sources.append({"kind": kind, **source})
        if kind == "funding":
            funding.update(read_zip(source["local"], parse_funding))
        else:
            metrics.update((moment, values) for moment, *values in read_zip(source["local"], parse_metrics))
    if not funding or not metrics:
        raise ValueError("Funding ou métricas vazios")
    for name, header, rows in (("funding.csv", ["time", "rate"], sorted(funding.items())),
                               ("metrics.csv", ["time", "open_interest", "taker_ratio"],
                                [(t, *v) for t, v in sorted(metrics.items())])):
        temporary = output / (name + ".part")
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(rows)
        temporary.replace(output / name)
    utc = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
    manifest = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(), "as_of": as_of.isoformat(),
                "source": "https://github.com/binance/binance-public-data (futuros USDⓈ-M, BTCUSDT)",
                "files": len(sources), "funding_rows": len(funding), "metrics_rows": len(metrics),
                "funding_coverage": [utc(min(funding)), utc(max(funding))],
                "metrics_coverage": [utc(min(metrics)), utc(max(metrics))],
                "assumptions": {"metrics_delay_seconds": METRICS_DELAY,
                                "funding": "disponível no instante de liquidação (calc_time)",
                                "liquidations": "não incluídas: sem série histórica pública contínua"},
                "products": {name: sha256(output / name) for name in ("funding.csv", "metrics.csv")},
                "raw": [{key: s[key] for key in ("kind", "key", "sha256", "url")} for s in sources]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


class DerivativeSeries:
    """Atributos causais: usa somente registros já disponíveis no instante pedido."""

    def __init__(self):
        self.funding_times, self.funding = [], []
        self.metrics_times, self.open_interest, self.taker = [], [], []

    @classmethod
    def from_folder(cls, folder):
        series = cls()
        folder = Path(folder)
        if (folder / "funding.csv").exists():
            with (folder / "funding.csv").open(encoding="utf-8", newline="") as stream:
                for row in csv.DictReader(stream):
                    series.add_funding(int(row["time"]), float(row["rate"]))
        if (folder / "metrics.csv").exists():
            with (folder / "metrics.csv").open(encoding="utf-8", newline="") as stream:
                for row in csv.DictReader(stream):
                    series.add_metrics(int(row["time"]), float(row["open_interest"]), float(row["taker_ratio"]))
        return series

    def add_funding(self, moment, rate):
        if not self.funding_times or moment > self.funding_times[-1]:
            self.funding_times.append(moment)
            self.funding.append(rate)

    def add_metrics(self, moment, open_interest, taker):
        if not self.metrics_times or moment > self.metrics_times[-1]:
            self.metrics_times.append(moment)
            self.open_interest.append(open_interest)
            self.taker.append(taker)

    def _metrics_at(self, moment):
        """Índice do último registro disponível em moment e ainda recente, ou None."""
        index = bisect_right(self.metrics_times, moment - METRICS_DELAY) - 1
        if index < 0 or moment - METRICS_DELAY - self.metrics_times[index] > METRICS_MAX_AGE:
            return None
        return index

    def features(self, moment):
        """Vetor na ordem de FEATURES para uma decisão disponível em moment (epoch, s)."""
        values = [0.0] * len(FEATURES)
        index = bisect_right(self.funding_times, moment) - 1
        if index >= 0 and moment - self.funding_times[index] <= FUNDING_MAX_AGE:
            values[0] = self.funding[index] * 10000
            values[1] = (moment - self.funding_times[index]) / (8 * 3600)
            values[6] = 1.0
        now = self._metrics_at(moment)
        past = [self._metrics_at(moment - lag) for lag in OI_LAGS]
        if now is not None and all(p is not None for p in past):
            for i, p in enumerate(past):
                values[2 + i] = 100 * math.log(self.open_interest[now] / self.open_interest[p])
            values[5] = math.log(self.taker[now])
            values[7] = 1.0
        return values


def _get(url):
    with urlopen(Request(url, headers={"User-Agent": "QuantLab-paper/1.0"}), timeout=20) as source:
        return json.load(source)


def fetch_live(get=_get):
    """Registros recentes da API pública, nos mesmos formatos do histórico."""
    funding = [(int(r["fundingTime"]) // 1000, float(r["fundingRate"])) for r in get(LIVE["funding"])]
    oi = {int(r["timestamp"]) // 1000: float(r["sumOpenInterest"]) for r in get(LIVE["open_interest"])}
    taker = {int(r["timestamp"]) // 1000: float(r["buySellRatio"]) for r in get(LIVE["taker"])}
    metrics = [(t, oi[t], taker[t]) for t in sorted(oi) if t in taker and oi[t] > 0 and taker[t] > 0]
    return sorted(funding), metrics


async def live_derivatives(series, on_status=None, interval=60, get=_get):
    """Atualiza a série a cada minuto; falhas só tiram a cobertura, nunca inventam valores."""
    failing = False
    while True:
        try:
            funding, metrics = await asyncio.to_thread(fetch_live, get)
            for row in funding:
                series.add_funding(*row)
            for row in metrics:
                series.add_metrics(*row)
            if failing and on_status:
                on_status("derivativos restabelecidos")
            failing = False
        except (OSError, ValueError, KeyError) as error:
            if not failing and on_status:
                on_status(f"derivativos indisponíveis: {error}")
            failing = True
        await asyncio.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "data" / "derivatives")
    args = parser.parse_args()
    started = time.monotonic()
    print(json.dumps(build(args.out, args.as_of), indent=2, ensure_ascii=False))
    print(f"Concluído em {time.monotonic() - started:.0f}s")
