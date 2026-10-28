"""Audita o dataset concluído e extrai nove janelas distribuídas pelo histórico."""

import argparse
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path

from bitcoin_data import FIELDS, sha256


def preview_svg(output, samples):
    elements = ['<svg xmlns="http://www.w3.org/2000/svg" width="1050" height="660" role="img" aria-labelledby="title">',
                '<title id="title">Nove janelas reais de 30 minutos: candles de 1 minuto e linha de fechamento</title>',
                '<rect width="1050" height="660" fill="white"/>',
                '<text x="20" y="25" font-family="sans-serif" font-size="17">BTC/USDT: 30 candles de 1 minuto por janela; linha azul = fechamento</text>']
    for index, row in enumerate(samples):
        x0, y0 = 20 + index % 3 * 345, 55 + index // 3 * 200
        low = min(float(row[f"low_{i:02}"]) for i in range(30))
        high = max(float(row[f"high_{i:02}"]) for i in range(30))
        span = high - low or 1
        def y(value):
            return y0 + 145 - (float(value) - low) / span * 110
        elements.append(f'<text x="{x0}" y="{y0}" font-family="sans-serif" font-size="12">{row["start_utc"]} | USDT</text>')
        points = []
        for offset in range(30):
            x = x0 + 10 + offset * 10
            opening, closing = float(row[f"open_{offset:02}"]), float(row[f"close_{offset:02}"])
            color = "#087f5b" if closing >= opening else "#c92a2a"
            elements.append(f'<line x1="{x}" x2="{x}" y1="{y(row[f"high_{offset:02}"]):.2f}" y2="{y(row[f"low_{offset:02}"]):.2f}" stroke="{color}"/>')
            elements.append(f'<rect x="{x-2}" y="{min(y(opening),y(closing)):.2f}" width="4" height="{max(1,abs(y(opening)-y(closing))):.2f}" fill="{color}"/>')
            points.append(f"{x},{y(closing):.2f}")
        elements.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="#2455a4" stroke-width="1.2"/>')
        elements.append(f'<text x="{x0}" y="{y0+166}" font-family="sans-serif" font-size="11">Min {low:.2f} | Max {high:.2f} | escala local por painel</text>')
    elements.append('</svg>')
    (output / "preview.svg").write_text("\n".join(elements), encoding="utf-8")


def audit(output):
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    quality = manifest["quality"]
    for product in quality["products"]:
        path = output / product["path"]
        if path.stat().st_size != product["bytes"] or sha256(path) != product["sha256"]:
            raise ValueError(f"Produto alterado: {path.name}")
    selected = {i * (quality["windows"] - 1) // 8 for i in range(9)}
    samples, expected, previous_end = [], {}, None
    with (output / "snapshots_30m.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames
        count = 0
        for index, row in enumerate(reader):
            start = datetime.fromisoformat(row["start_utc"])
            end = datetime.fromisoformat(row["available_at_utc"])
            if int(row["window_id"]) != index or row["samples"] != "30" or end - start != timedelta(minutes=30):
                raise ValueError(f"Contrato de janela inválido: {index}")
            if previous_end is not None and start < previous_end:
                raise ValueError("Janelas se sobrepõem")
            previous_end = end
            if index in selected:
                samples.append(row)
                for offset in range(30):
                    key = (start + timedelta(minutes=offset)).isoformat().replace("+00:00", "Z")
                    expected[key] = tuple(row[f"{field}_{offset:02}"] for field in FIELDS)
            count += 1
    if count != quality["windows"]:
        raise ValueError("Contagem de janelas divergente")
    found, previous, normalized_count = 0, None, 0
    with (output / "btc_usdt_1m.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            key = row["timestamp"]
            if previous is not None and key <= previous:
                raise ValueError("Histórico de um minuto fora de ordem")
            previous = key
            if key in expected:
                if tuple(row[field] for field in FIELDS) != expected[key]:
                    raise ValueError(f"Snapshot diverge do histórico: {key}")
                found += 1
            normalized_count += 1
    if normalized_count != quality["candles"] or found != len(expected):
        raise ValueError("Contagem de candles ou correspondência de amostras divergente")
    split_counts = {"train": 0, "validation": 0, "test": 0}
    previous_rank = 0
    with (output / "splits.csv").open(encoding="utf-8", newline="") as stream:
        count = 0
        for index, row in enumerate(csv.DictReader(stream)):
            rank = {"train": 0, "validation": 1, "test": 2}[row["split"]]
            if rank < previous_rank or int(row["window_id"]) != index:
                raise ValueError("Divisão temporal fora de ordem")
            previous_rank = rank
            split_counts[row["split"]] += 1
            count += 1
    if count != quality["windows"] or split_counts != quality["splits"]:
        raise ValueError("Divisões não correspondem ao manifesto")
    with (output / "preview_snapshots.csv").open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=headers)
        writer.writeheader()
        writer.writerows(samples)
    preview_svg(output, samples)
    report = {"status": "passed", "candles_checked": normalized_count,
              "windows_checked": quality["windows"], "sample_windows_matched_to_history": len(samples),
              "sample_minutes_matched": found, "derived_file_hashes_verified": len(quality["products"]),
              "split_counts": split_counts}
    (output / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    audit(parser.parse_args().directory)
