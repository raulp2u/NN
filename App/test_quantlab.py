import csv
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import tempfile
import unittest

from quantlab import Candle, load_csv, simulate, targets, validate


def candles(prices, opens=None):
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    opens = opens or prices
    return [Candle(start + timedelta(hours=i), o, max(o, c), min(o, c), c, 1)
            for i, (o, c) in enumerate(zip(opens, prices))]


class SimulatorTests(unittest.TestCase):
    def test_execution_uses_next_open_and_accounts_for_gap(self):
        data = candles([100, 120, 150], [100, 110, 140])
        summary, rows, trades = simulate(data, [1, 0, 0], initial=1000, fee_bps=0, slippage_bps=0)
        self.assertEqual(rows[0]["units"], 0)
        self.assertEqual(trades[0]["price"], 110)
        self.assertEqual(trades[1]["price"], 140)
        self.assertAlmostEqual(summary["final_liquidated"], 1000 * 140 / 110)

    def test_flat_price_round_trip_costs(self):
        summary, _, trades = simulate(candles([100] * 3), [1, 0, 0], initial=1000,
                                      fee_bps=10, slippage_bps=5)
        expected = 1000 / (1.0005 * 1.001) * .9995 * .999
        self.assertAlmostEqual(summary["final_liquidated"], expected)
        self.assertEqual(len(trades), 2)
        self.assertLess(summary["net_return"], 0)
        self.assertFalse(summary["terminal_liquidation"])

    def test_terminal_exit_has_cost_and_is_separate(self):
        summary, rows, _ = simulate(candles([100, 100]), [1, 1], initial=1000,
                                   fee_bps=10, slippage_bps=5)
        expected = 1000 / (1.0005 * 1.001) * .9995 * .999
        self.assertAlmostEqual(summary["final_liquidated"], expected)
        self.assertTrue(summary["terminal_liquidation"])
        self.assertGreater(rows[-1]["equity_marked"], summary["final_liquidated"])
        self.assertEqual(summary["last_signal_for_next_open"], "AGUARDAR")

    def test_final_signal_is_not_executed_retroactively(self):
        summary, _, trades = simulate(candles([100, 110]), [None, 1])
        self.assertEqual(trades, [])
        self.assertEqual(summary["last_signal_for_next_open"], "COMPRAR")

    def test_drawdown_from_peak(self):
        summary, _, _ = simulate(candles([100, 100, 120, 60]), [1] * 4,
                                  fee_bps=0, slippage_bps=0)
        self.assertAlmostEqual(summary["max_drawdown"], .5)

    def test_no_short_when_sell_target_and_flat(self):
        summary, rows, trades = simulate(candles([100, 80, 60]), [0, 0, 0])
        self.assertEqual(trades, [])
        self.assertTrue(all(r["units"] == 0 for r in rows))
        self.assertEqual(summary["net_return"], 0)

    def test_future_does_not_change_past_signals_or_positions(self):
        data = candles([100, 103, 101, 105, 90, 95, 110, 115, 70])
        full_targets = targets(data, 2, 3)
        prefix_targets = targets(data[:6], 2, 3)
        self.assertEqual(full_targets[:6], prefix_targets)
        _, full_rows, _ = simulate(data, full_targets)
        _, prefix_rows, _ = simulate(data[:6], prefix_targets)
        self.assertEqual(full_rows[:6], prefix_rows)

    def test_invalid_configuration(self):
        for config in ({"fee_bps": -1}, {"slippage_bps": 10000}, {"initial": math.nan}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                simulate(candles([100, 100]), [1, 0], **config)
        with self.assertRaises(ValueError):
            targets(candles([100]), 3, 2)


class DataTests(unittest.TestCase):
    def test_bad_candles_rejected(self):
        base = candles([100, 101])
        invalid = [[], [base[1], base[0]], [base[0], base[0]],
                   [base[0], candles([100, 101, 102])[2]],
                   [Candle(base[0].timestamp, 100, 99, 98, 100, 1)],
                   [Candle(base[0].timestamp, 100, 101, 99, math.nan, 1)],
                   [Candle(base[0].timestamp, 0, 101, 0, 100, 1)],
                   [Candle(base[0].timestamp.replace(tzinfo=None), 100, 101, 99, 100, 1)],
                   [Candle(datetime.now(timezone.utc) + timedelta(days=1), 100, 101, 99, 100, 1)]]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate(data)

    def test_csv_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
                writer.writerow(["2020-01-01T00:00:00Z", 100, 101, 99, 100, 1])
            self.assertEqual(load_csv(path)[0].close, 100)
            path.write_text("timestamp,close\n2020-01-01,100\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_csv(path)


if __name__ == "__main__":
    unittest.main()
