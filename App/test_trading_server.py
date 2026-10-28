from datetime import datetime, timezone
from importlib.util import find_spec
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from trading_engine import Bar, Engine, Settings
from trading_models import MovingAverageModel
from trading_sources import FxSeries, iso, parse_kline_message, read_history

T0 = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())


class SourceTests(unittest.TestCase):
    def test_only_closed_binance_klines_are_used(self):
        message = {"stream": "btcusdt@kline_1m", "data": {"e": "kline", "s": "BTCUSDT", "k": {
            "t": T0 * 1000, "T": T0 * 1000 + 59999, "s": "BTCUSDT", "i": "1m", "o": "100.0",
            "c": "101.0", "h": "102.0", "l": "99.0", "v": "3.5", "x": True}}}
        symbol, bar = parse_kline_message(json.dumps(message))
        self.assertEqual((symbol, bar), ("BTCUSDT", Bar(T0, 100., 102., 99., 101., 3.5)))
        message["data"]["k"]["x"] = False
        self.assertIsNone(parse_kline_message(message))
        self.assertIsNone(parse_kline_message({"data": {"e": "trade"}}))

    def test_fx_uses_only_closed_candles_and_expires(self):
        fx = FxSeries(max_age_minutes=5)
        fx.add(T0, 5.0)
        fx.add(T0 + 60, 5.1)
        self.assertIsNone(fx(T0))
        self.assertEqual(fx(T0 + 60), 5.0)
        self.assertEqual(fx(T0 + 120), 5.1)
        self.assertIsNone(fx(T0 + 120 + 6 * 60))
        self.assertEqual(FxSeries(fixed=5.4)(T0), 5.4)

    def test_history_reader_filters_period(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "btc.csv"
            lines = ["timestamp,open,high,low,close,volume"] + [f"{iso(T0 + 60 * i)},100,101,99,100,1" for i in range(5)]
            path.write_text("\n".join(lines), encoding="utf-8")
            self.assertEqual([b.open_time for b in read_history(path, T0 + 60, T0 + 180)], [T0 + 60, T0 + 120])


@unittest.skipIf(find_spec("fastapi") is None or find_spec("httpx") is None, "Requer requirements-interface.txt")
class ServerTests(unittest.TestCase):
    def setUp(self):
        from trading_server import EventLog, Runner, create_app
        self.folder = tempfile.TemporaryDirectory()
        self.db = Path(self.folder.name) / "session.sqlite"
        engine = Engine(MovingAverageModel(2, 3), Settings(horizon_minutes=None, levels=False))
        self.runner = Runner(engine, EventLog(self.db), {"mode": "replay", "model": "medias", "speed": 0})
        self.app = create_app(self.runner)

    def tearDown(self):
        self.runner.log.db.close()
        self.folder.cleanup()

    def feed(self, prices):
        for i, price in enumerate(prices):
            self.runner.feed(Bar(T0 + 60 * i, price, price, price, price, 1.))

    def test_state_events_stats_and_websocket_backlog(self):
        from fastapi.testclient import TestClient
        self.feed([100, 101, 102, 103, 101, 99, 98, 100, 103])
        with TestClient(self.app) as client:
            session = client.get("/api/session").json()
            self.assertTrue(session["paused"])
            events = client.get("/api/events").json()
            self.assertEqual([e["seq"] for e in events], list(range(1, len(events) + 1)))
            self.assertIn("trade", {e["kind"] for e in events})
            stats = client.get("/api/stats").json()
            self.assertEqual(stats["trading"]["trades"], len(self.runner.engine.trades))
            with client.websocket_connect("/ws?after=3") as socket:
                backlog = json.loads(socket.receive_text())
            self.assertEqual(backlog[0]["seq"], 4)
            self.assertEqual(client.post("/api/control", json={"action": "speed", "value": 10}).json()["speed"], 10)
            self.assertEqual(client.post("/api/control", json={"action": "x"}).status_code, 400)
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/static/app.js").status_code, 200)

    def test_log_is_append_only(self):
        self.feed([100, 101])
        with self.assertRaises(sqlite3.DatabaseError):
            self.runner.log.db.execute("UPDATE events SET kind = 'x'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.runner.log.db.execute("DELETE FROM events")

    def test_test_split_detection(self):
        from trading_server import split_overlap
        boundaries = {"train": {"first_start_utc": iso(T0), "last_available_at_utc": iso(T0 + 3600)},
                      "validation": {"first_start_utc": iso(T0 + 3600), "last_available_at_utc": iso(T0 + 7200)},
                      "test": {"first_start_utc": iso(T0 + 7200), "last_available_at_utc": iso(T0 + 10800)}}
        self.assertEqual(split_overlap(T0 + 3600, T0 + 7200, boundaries), ["validation"])
        self.assertEqual(split_overlap(T0 + 7000, T0 + 7300, boundaries), ["validation", "test"])
        self.assertIn("fora_do_dataset", split_overlap(T0 + 10000, T0 + 20000, boundaries))


if __name__ == "__main__":
    unittest.main()
