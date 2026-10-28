import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from bitcoin_data import MINUTE, Windows, build, parse_row, select_files, timestamp_ms, verify_hash
from audit_bitcoin_data import audit


START = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()) * 1000


def source_row(timestamp, microseconds=False):
    unit = 1000 if microseconds else 1
    return [str(timestamp * unit), "100", "101", "99", "100.5", "2",
            str((timestamp + MINUTE) * unit - 1), "200", "10", "1", "100", "0"]


def archive(folder, timestamps):
    path = folder / "BTCUSDT-1m-2024-01.zip"
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerows(source_row(t) for t in timestamps)
    with ZipFile(path, "w") as output:
        output.writestr("BTCUSDT-1m-2024-01.csv", buffer.getvalue())
    return [{"local": str(path)}]


class ParsingTests(unittest.TestCase):
    def test_ms_and_microseconds(self):
        timestamp = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()) * 1000
        self.assertEqual(timestamp_ms(str(timestamp)), timestamp)
        self.assertEqual(timestamp_ms(str(timestamp * 1000)), timestamp)
        self.assertEqual(parse_row(source_row(timestamp)), parse_row(source_row(timestamp, True)))

    def test_bad_prices_times_and_nonfinite(self):
        for column, value in [(0, str(START + 1)), (6, str(START + MINUTE)),
                              (1, "nan"), (2, "99"), (5, "-2")]:
            row = source_row(START)
            row[column] = value
            with self.subTest(column=column), self.assertRaises(ValueError):
                parse_row(row)

    def test_corruption_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.zip"
            path.write_bytes(b"original")
            expected = hashlib.sha256(b"original").hexdigest()
            self.assertEqual(verify_hash(path, expected), expected)
            path.write_bytes(b"corrupted")
            with self.assertRaises(ValueError):
                verify_hash(path, expected)

    def test_current_day_is_excluded_and_month_not_duplicated(self):
        def fake_catalog(prefix):
            if "monthly" in prefix:
                return [{"key": "BTCUSDT-1m-2026-09.zip", "size": 1},
                        {"key": "BTCUSDT-1m-2026-10.zip", "size": 1}]
            return [{"key": f"BTCUSDT-1m-2026-10-{day}.zip", "size": 1} for day in ("26", "27")]
        with patch("bitcoin_data.catalog", side_effect=fake_catalog):
            from datetime import date
            selected = select_files(date(2026, 10, 27))
        self.assertEqual([item["key"] for item in selected],
                         ["BTCUSDT-1m-2026-09.zip", "BTCUSDT-1m-2026-10-26.zip"])


class WindowTests(unittest.TestCase):
    def test_no_incomplete_or_future_window(self):
        windows = Windows()
        for i in range(29):
            self.assertIsNone(windows.push(START + i * MINUTE, (str(i),) * 5))
        completed = windows.push(START + 29 * MINUTE, ("29",) * 5)
        self.assertEqual(len(completed), 30)
        past = tuple(completed)
        windows.push(START + 30 * MINUTE, ("FUTURE",) * 5)
        self.assertEqual(tuple(completed), past)

    def test_gaps_exclude_windows_without_interpolation(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            timestamps = [START + i * MINUTE for i in range(60) if i != 5]
            result = build(output, archive(output, timestamps), datetime(2024, 1, 2).date())
            self.assertEqual(result["candles"], 59)
            self.assertEqual(result["windows"], 1)
            self.assertEqual(result["missing_minutes"], 1)
            self.assertEqual(result["incomplete_buckets_excluded"], 1)
            self.assertEqual(result["candles_not_in_complete_windows"], 29)

    def test_split_boundaries_and_snapshot_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            result = build(output, archive(output, [START + i * MINUTE for i in range(300)]),
                           datetime(2024, 1, 2).date())
            self.assertEqual(result["splits"], {"train": 8, "validation": 1, "test": 1})
            boundaries = result["split_boundaries"]
            self.assertLessEqual(boundaries["train"]["last_available_at_utc"],
                                 boundaries["validation"]["first_start_utc"])
            with (output / "snapshots_30m.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["start_utc"], "2024-01-01T00:00:00Z")
            self.assertEqual(rows[0]["available_at_utc"], "2024-01-01T00:30:00Z")
            self.assertEqual(rows[0]["close_29"], "100.5")
            self.assertNotIn("close_30", rows[0])
            self.assertEqual(len(rows[0]), 154)

    def test_duplicate_fails_before_publishing_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            with self.assertRaises(ValueError):
                build(output, archive(output, [START, START]), datetime(2024, 1, 2).date())
            self.assertFalse((output / "snapshots_30m.csv").exists())

    def test_bad_source_row_is_quarantined_and_window_excluded(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            rows = [source_row(START + i * MINUTE) for i in range(60)]
            rows[5][6] = str(START + 6 * MINUTE)  # anomalia de fechamento observada no arquivo real
            buffer = io.StringIO(newline="")
            csv.writer(buffer).writerows(rows)
            path = output / "BTCUSDT-1m-2024-01.zip"
            with ZipFile(path, "w") as stream:
                stream.writestr(path.with_suffix(".csv").name, buffer.getvalue())
            result = build(output, [{"local": str(path)}], datetime(2024, 1, 2).date())
            self.assertEqual(result["raw_rows"], 60)
            self.assertEqual(result["quarantined_rows"], 1)
            self.assertEqual(result["windows"], 1)
            with (output / "quarantine.csv").open(encoding="utf-8", newline="") as stream:
                rejected = list(csv.DictReader(stream))
            self.assertEqual(rejected[0]["line"], "6")
            self.assertIn("Fechamento", rejected[0]["reason"])

    def test_independent_audit_and_detect_modified_product(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            quality = build(output, archive(output, [START + i * MINUTE for i in range(300)]),
                            datetime(2024, 1, 2).date())
            (output / "manifest.json").write_text(json.dumps({"quality": quality}), encoding="utf-8")
            audit(output)
            result = json.loads((output / "audit.json").read_text(encoding="utf-8"))
            self.assertEqual(result["sample_minutes_matched"], 270)
            self.assertEqual(result["windows_checked"], 10)
            ET.parse(output / "preview.svg")
            with (output / "snapshots_30m.csv").open("a", encoding="utf-8") as stream:
                stream.write("alterado\n")
            with self.assertRaisesRegex(ValueError, "Produto alterado"):
                audit(output)


if __name__ == "__main__":
    unittest.main()
