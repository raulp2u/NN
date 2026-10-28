"""Cria candles artificiais para demonstrar o programa, nunca para validar lucro."""

import csv
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path


def main():
    output = Path(__file__).parent / "examples" / "synthetic.csv"
    output.parent.mkdir(exist_ok=True)
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    previous = 100.0
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for i in range(160):
            close = round(100 + 12 * math.sin(i / 9) + i / 30, 6)
            writer.writerow([(start + timedelta(hours=i)).isoformat(), previous,
                             max(previous, close) + 1, min(previous, close) - 1, close, 100])
            previous = close
    print(output)


if __name__ == "__main__":
    main()
