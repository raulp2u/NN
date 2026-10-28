from datetime import datetime, timezone
import asyncio
from importlib.util import find_spec
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from trading_engine import Bar, Engine, Settings
from trading_models import MovingAverageModel
from trading_sources import FxSeries, iso, live_bars, parse_kline_message, read_history

T0 = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())


class SourceTests(unittest.TestCase):
    def test_live_start_is_ready_from_history_and_backfill_cannot_place_orders(self):
        now = T0 + 60 * 60
        initial = [Bar(now - 1800 + i * 60, 100 + i, 100 + i, 100 + i, 100 + i, 1)
                   for i in range(30)]
        recovered = [Bar(now, 130, 130, 130, 130, 1)]
        fx = FxSeries()
        engine = Engine(MovingAverageModel(2, 3), Settings(levels=False), fx=fx)
        calls, events, order = [], [], []

        def fetch(symbol, start, end):
            order.append(symbol)
            if symbol == "USDTBRL":
                return [Bar(now - 120, 5, 5, 5, 5, 1), Bar(now - 60, 5, 5, 5, 5, 1)]
            if start == now - 1800:
                return initial
            return recovered

        def feed(bar, warmup):
            calls.append((bar.open_time, warmup))
            engine.warming = warmup
            events.extend(engine.on_bar(bar))

        async def messages():
            yield {"e": "kline", "k": {"s": "BTCUSDT", "i": "1m", "x": True,
                    "t": (now + 60) * 1000, "o": "131", "h": "131", "l": "131", "c": "131", "v": "1"}}
            raise asyncio.CancelledError

        socket = AsyncMock()
        socket.__aiter__.side_effect = messages
        context = AsyncMock()
        context.__aenter__.return_value = socket
        clock_values = iter([now, now, now + 120])
        with patch("trading_sources.fetch_closed", side_effect=fetch), \
             patch("trading_sources.time.time", side_effect=lambda: next(clock_values)), \
             patch("websockets.connect", return_value=context):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(live_bars("BTCUSDT", feed, on_fx=lambda b: fx.add(b.open_time, b.close)))
        self.assertEqual(order[:2], ["USDTBRL", "BTCUSDT"])
        self.assertTrue(all(warm for _, warm in calls[:29]))
        self.assertEqual(calls[29], (now - 60, False))
        self.assertEqual(calls[30:], [(now, True), (now + 60, False)])
        # A decisão inicial está pronta; a ordem pendente foi cancelada durante a recuperação.
        initial_decision = next(e for e in events if e["kind"] == "decision" and e["time"] == now - 60)
        self.assertEqual(initial_decision["action"], "COMPRAR")
        self.assertFalse(any(e["kind"] == "order" for e in events))

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
            self.assertAlmostEqual(stats["trading"]["net_display"], self.runner.engine.realized_display)
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

    def test_replay_warmup_loads_window_without_orders(self):
        prices = [100, 101, 102, 103, 101, 99, 98, 100, 103, 104, 99]
        bars = [Bar(T0 + 60 * i, p, p, p, p, 1.) for i, p in enumerate(prices)]
        self.runner.paused = False
        self.runner.replay(iter(bars), start=T0 + 60 * 6)
        events = self.runner.log.since()
        orders = [e for e in events if e["kind"] == "order"]
        self.assertTrue(orders)
        self.assertTrue(all(e["time"] >= T0 + 60 * 7 for e in orders))
        warm = [e for e in events if e["kind"] == "decision" and e["time"] < T0 + 60 * 6]
        self.assertTrue(warm and all(e["action"] == "AQUECIMENTO" for e in warm))
        first = next(e for e in events if e["kind"] == "decision" and e["time"] == T0 + 60 * 6)
        self.assertNotEqual(first["action"], "AQUECIMENTO")

    def test_prediction_quality_reports_calibration_and_interval(self):
        from trading_server import prediction_quality
        outcome = lambda category, p_target, inside: {
            "predicted": .001, "realized": .002, "error": -.001, "category": category, "side": 1, "inside_interval": inside,
            "probabilities": {"p_target": p_target, "p_stop": .9 - p_target, "p_time": .1}}
        quality = prediction_quality([outcome("alvo", .65, True), outcome("stop", .7, True), outcome("alvo", .1, False)])
        self.assertAlmostEqual(quality["interval_coverage"], 2 / 3)
        rows = {(r["category"], r["bin"][0]): r for r in quality["calibration"]["table"]}
        self.assertEqual(rows[("alvo", .6)]["count"], 2)
        self.assertAlmostEqual(rows[("alvo", .6)]["observed"], .5)
        self.assertAlmostEqual(rows[("alvo", .6)]["predicted"], .675)
        self.assertNotIn("calibration", prediction_quality([{"predicted": 0., "realized": 0., "error": 0.}]))


if __name__ == "__main__":
    unittest.main()
