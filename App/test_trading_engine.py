from datetime import datetime, timezone
import math
from importlib.util import find_spec
import random
import unittest

from quantlab import Candle, simulate, targets
from trading_engine import Bar, Engine, Settings, Signal, performance
from trading_models import MovingAverageModel

T0 = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
FEE, SLIP = .001, .0005


class Scripted:
    """Modelo de oportunidade: sinais fixos por minuto de fechamento."""
    level_triggered = False
    window = 1

    def __init__(self, signals):
        self.signals, self.resets = signals, 0

    def reset(self):
        self.resets += 1

    def update(self, bar):
        return self.signals.get(bar.open_time)


def bar(minute, o, h=None, low=None, c=None):
    c = o if c is None else c
    return Bar(T0 + 60 * minute, o, max(o, c) if h is None else h, min(o, c) if low is None else low, c, 1.)


def run(engine, bars):
    return [event for b in bars for event in engine.on_bar(b)]


def kinds(events, kind):
    return [e for e in events if e["kind"] == kind]


LONG = Signal(1, "teste")
SHORT = Signal(-1, "teste")
PLAIN = dict(levels=False, borrow_bps_per_hour=0)


class AccountingTests(unittest.TestCase):
    def test_fx_expiration_cancels_pending_entry(self):
        engine = Engine(Scripted({T0: LONG}), Settings(**PLAIN),
                        fx=lambda t: 5.0 if t == T0 else None)
        engine.on_bar(bar(0, 100))
        events = engine.on_bar(bar(1, 100))
        self.assertIsNone(engine.position)
        self.assertIsNone(engine.pending)
        self.assertIn("order_cancelled", [e["code"] for e in kinds(events, "alert")])

    def test_long_fixed_stake_timeout_at_close(self):
        engine = Engine(Scripted({T0: LONG}), Settings(horizon_minutes=2, **PLAIN))
        events = run(engine, [bar(0, 99), bar(1, 100, c=101), bar(2, 101, c=102), bar(3, 102)])
        trade = kinds(events, "trade")[0]
        units = 50 / (100 * (1 + SLIP) * (1 + FEE))
        self.assertAlmostEqual(trade["units"], units)
        self.assertEqual((trade["entry_time"], trade["exit_time"]), (T0 + 60, T0 + 180))
        self.assertEqual((trade["exit_reason"], trade["exit_moment"]), ("tempo", "close"))
        expected = units * 102 * (1 - SLIP) * (1 - FEE) - 50
        self.assertAlmostEqual(trade["net_quote"], expected)
        self.assertAlmostEqual(trade["gross_quote"] - trade["fees_quote"] - trade["slippage_quote"], expected)
        self.assertAlmostEqual(engine.realized, expected)

    def test_short_with_borrow_cost(self):
        settings = Settings(horizon_minutes=2, levels=False, borrow_bps_per_hour=1)
        engine = Engine(Scripted({T0: SHORT}), settings)
        trade = kinds(run(engine, [bar(0, 99), bar(1, 100, c=99), bar(2, 99, c=98), bar(3, 98)]), "trade")[0]
        entry, exit_price = 100 * (1 - SLIP), 98 * (1 + SLIP)
        units = 50 / entry
        borrow = 50 * .0001 * 2 / 60
        self.assertEqual(trade["side"], "vendida")
        self.assertAlmostEqual(trade["borrow_quote"], borrow)
        self.assertAlmostEqual(trade["net_quote"], units * (entry * (1 - FEE) - exit_price * (1 + FEE)) - borrow)
        self.assertGreater(trade["net_quote"], 0)

    def test_display_currency_and_fx_effect(self):
        rates = {T0 + 60: 5.0, T0 + 120: 5.0, T0 + 180: 5.5}
        engine = Engine(Scripted({T0: LONG}), Settings(horizon_minutes=3, **PLAIN), fx=lambda t: rates.get(t, 5.0))
        trade = kinds(run(engine, [bar(0, 100), bar(1, 100), bar(2, 100), bar(3, 100), bar(4, 100)]), "trade")[0]
        self.assertAlmostEqual(trade["stake_quote"], 10)
        self.assertAlmostEqual(trade["net_display"], (10 + trade["net_quote"]) * 5.5 - 50)
        self.assertAlmostEqual(trade["fx_effect_display"], trade["net_display"] - 5 * trade["net_quote"])
        self.assertGreater(trade["fx_effect_display"], 0)

    def test_missing_fx_blocks_entry(self):
        engine = Engine(Scripted({T0: LONG}), Settings(**PLAIN), fx=lambda t: None)
        events = run(engine, [bar(0, 100), bar(1, 100)])
        self.assertEqual(kinds(events, "decision")[0]["action"], "AGUARDAR")
        self.assertFalse(kinds(events, "order"))
        self.assertEqual(kinds(events, "alert")[0]["code"], "fx_missing")


class LevelTests(unittest.TestCase):
    def open_long(self, *bars, **levels):
        signal = Signal(1, "teste", stop_distance=math.log(100 / 99), target_distance=math.log(101 / 100), **levels)
        engine = Engine(Scripted({T0: signal}), Settings(horizon_minutes=30, borrow_bps_per_hour=0))
        return engine, run(engine, [bar(0, 100), *bars])

    def test_stop_inside_entry_candle(self):
        _, events = self.open_long(bar(1, 100, h=100.5, low=98.5, c=99.5))
        trade = kinds(events, "trade")[0]
        self.assertEqual((trade["exit_reason"], trade["exit_moment"]), ("stop", "intrabar"))
        self.assertAlmostEqual(trade["exit_raw"], 99)
        self.assertAlmostEqual(trade["exit_price"], 99 * (1 - SLIP))
        self.assertEqual(trade["levels_source"], "modelo")
        self.assertFalse(trade["ambiguous"])

    def test_target_and_same_candle_ambiguity_assumes_stop(self):
        _, events = self.open_long(bar(1, 100, h=100.5, low=99.5), bar(2, 100, h=101.2, low=99.8))
        self.assertEqual(kinds(events, "trade")[0]["exit_reason"], "alvo")
        self.assertAlmostEqual(kinds(events, "trade")[0]["exit_raw"], 101)
        _, events = self.open_long(bar(1, 100, h=101.5, low=98.5))
        trade = kinds(events, "trade")[0]
        self.assertEqual(trade["exit_reason"], "stop")
        self.assertTrue(trade["ambiguous"])

    def test_open_beyond_stop_executes_at_open(self):
        _, events = self.open_long(bar(1, 100, h=100.2, low=99.6), bar(2, 98, h=98.4, low=97.5))
        trade = kinds(events, "trade")[0]
        self.assertEqual((trade["exit_reason"], trade["exit_moment"], trade["exit_raw"]), ("stop", "open", 98))

    def test_provisional_levels_from_past_volatility(self):
        closes = [100, 101, 100, 102, 101]
        engine = Engine(Scripted({T0 + 240: LONG}), Settings(stop_k=2, target_k=3, borrow_bps_per_hour=0))
        events = run(engine, [bar(i, c) for i, c in enumerate(closes)] + [bar(5, 101)])
        order = kinds(events, "order")[0]
        returns = [math.log(b / a) for a, b in zip(closes, closes[1:])]
        mean = sum(returns) / 4
        sigma = math.sqrt(sum((r - mean) ** 2 for r in returns) / 3 * 30)
        self.assertAlmostEqual(order["stop"], 101 * math.exp(-2 * sigma))
        self.assertAlmostEqual(order["target"], 101 * math.exp(3 * sigma))
        self.assertEqual(order["levels_source"], "provisorio_volatilidade")


class PolicyTests(unittest.TestCase):
    def decide(self, predicted, **settings):
        signal = Signal(None, "cnn", predicted_log_return=predicted, horizon_minutes=30)
        engine = Engine(Scripted({T0: signal}), Settings(**{**PLAIN, **settings}))
        return kinds(engine.on_bar(bar(0, 100)), "decision")[0]

    def test_cost_hurdle_both_sides(self):
        hurdle = Settings().hurdle(1)
        self.assertAlmostEqual(hurdle, math.log(1.001 / .999) + math.log(1.0005 / .9995))
        self.assertEqual(self.decide(hurdle * .99)["action"], "AGUARDAR")
        self.assertEqual(self.decide(hurdle * 1.01)["action"], "COMPRAR")
        self.assertEqual(self.decide(-hurdle * 1.01)["action"], "VENDER A DESCOBERTO")
        self.assertEqual(self.decide(-hurdle * 1.01, allow_short=False)["action"], "AGUARDAR")
        self.assertGreater(Settings(borrow_bps_per_hour=1).hurdle(-1, 30), hurdle)

    def test_reversal_closes_then_opens(self):
        engine = Engine(Scripted({T0: LONG, T0 + 60: SHORT}), Settings(**PLAIN))
        events = run(engine, [bar(0, 100), bar(1, 100), bar(2, 100)])
        orders = [(e["action"], e["side"], e["time"]) for e in kinds(events, "order")]
        self.assertEqual(orders, [("abrir", "comprada", T0 + 60), ("fechar", "comprada", T0 + 120),
                                  ("abrir", "vendida", T0 + 120)])
        self.assertEqual(kinds(events, "decision")[1]["action"], "INVERTER: VENDER A DESCOBERTO")

    def test_gap_closes_position_resets_model_and_cancels_order(self):
        model = Scripted({T0: LONG, T0 + 60: SHORT})
        engine = Engine(model, Settings(**PLAIN))
        events = run(engine, [bar(0, 100), bar(1, 100), bar(3, 97)])
        trade = kinds(events, "trade")[0]
        self.assertEqual((trade["exit_reason"], trade["exit_raw"]), ("lacuna", 97))
        self.assertEqual([e["code"] for e in kinds(events, "alert")], ["gap", "order_cancelled"])
        self.assertEqual(model.resets, 1)
        self.assertEqual(len(kinds(events, "order")), 2)

    def test_warmup_records_decision_without_orders(self):
        engine = Engine(Scripted({T0: LONG}), Settings(**PLAIN))
        engine.warming = True
        events = engine.on_bar(bar(0, 100))
        engine.warming = False
        events += engine.on_bar(bar(1, 100))
        self.assertEqual(kinds(events, "decision")[0]["action"], "AQUECIMENTO")
        self.assertFalse(kinds(events, "order"))

    def test_rejects_out_of_order_and_invalid_bars(self):
        engine = Engine(Scripted({}), Settings())
        engine.on_bar(bar(1, 100))
        with self.assertRaises(ValueError):
            engine.on_bar(bar(1, 100))
        with self.assertRaises(ValueError):
            Engine(Scripted({}), Settings()).on_bar(Bar(T0, 100, 99, 98, 100, 1))


def random_walk(count, seed=7):
    rng = random.Random(seed)
    price, bars = 100., []
    for i in range(count):
        close = price * math.exp(rng.gauss(0, .004))
        bars.append(bar(i, price, max(price, close) * 1.001, min(price, close) * .999, close))
        price = close
    return bars


class EquivalenceTests(unittest.TestCase):
    def test_moving_average_trades_match_quantlab(self):
        bars = random_walk(400)
        candles = [Candle(datetime.fromtimestamp(b.open_time, timezone.utc), b.open, b.high, b.low, b.close, b.volume)
                   for b in bars]
        _, rows, reference = simulate(candles, targets(candles, 5, 20), initial=1000, fee_bps=10, slippage_bps=5)
        engine = Engine(MovingAverageModel(5, 20), Settings(allow_short=False, horizon_minutes=None, **PLAIN))
        run(engine, bars)
        self.assertGreater(len(engine.trades), 5)
        pairs = list(zip(reference[0::2], reference[1::2]))
        self.assertEqual(len(pairs), len(engine.trades))
        cash = {r["timestamp"]: r["cash"] for r in rows}
        for (buy, sell), trade in zip(pairs, engine.trades):
            self.assertEqual(buy["timestamp"], datetime.fromtimestamp(trade["entry_time"], timezone.utc).isoformat())
            self.assertEqual(sell["timestamp"], datetime.fromtimestamp(trade["exit_time"], timezone.utc).isoformat())
            self.assertAlmostEqual(buy["price"], trade["entry_price"])
            self.assertAlmostEqual(sell["price"], trade["exit_price"])
        # Retorno por operação idêntico; o quantlab reinveste, o motor usa valor fixo.
        start = 1000.
        for (_, sell), trade in zip(pairs, engine.trades):
            end = cash[sell["timestamp"]]
            self.assertAlmostEqual(end / start - 1, trade["net_pct"], places=12)
            start = end

    @unittest.skipIf(find_spec("torch") is None, "Requer requirements-torch-cpu.txt")
    def test_window_policy_matches_train_numeric_simulation(self):
        import numpy as np
        import polars as pl
        from train_numeric import simulated_policy
        bars = random_walk(30 * 40, seed=3)
        hurdle = Settings().hurdle(1)
        rng = random.Random(5)
        predictions = [rng.choice([0, hurdle * 2, -hurdle * 2, hurdle * .5]) for _ in range(40)]
        signals = {T0 + 60 * (30 * i + 29): Signal(None, "stub", predicted_log_return=p, horizon_minutes=30)
                   for i, p in enumerate(predictions)}
        engine = Engine(Scripted(signals), Settings(allow_short=False, horizon_minutes=30, **PLAIN))
        run(engine, bars)
        frame = pl.DataFrame({"execution_open_future": [bars[30 * (i + 1)].open for i in range(39)],
                              "exit_close_future": [bars[30 * (i + 1) + 29].close for i in range(39)]})
        reference, _ = simulated_policy(frame, np.array(predictions[:39]))
        self.assertEqual(reference["round_trips"], len(engine.trades))
        self.assertGreater(len(engine.trades), 3)
        compounded = math.prod(1 + t["net_pct"] for t in engine.trades) - 1
        self.assertAlmostEqual(reference["net_return"], compounded, places=12)


class CausalityTests(unittest.TestCase):
    def test_recovery_cancels_orders_and_does_not_execute_stops_in_the_past(self):
        signal = Signal(1, "test", stop_distance=.01, target_distance=.01)
        engine = Engine(Scripted({T0: signal, T0 + 120: SHORT}), Settings(**PLAIN))
        engine.on_bar(bar(0, 100))
        engine.warming = True
        recovered = engine.on_bar(bar(1, 100, h=120, low=80))
        self.assertFalse(kinds(recovered, "order"))
        self.assertIsNone(engine.position)

        # Uma posição que já existia antes da perda da conexão não sai num candle recuperado.
        engine = Engine(Scripted({T0: signal, T0 + 120: SHORT}), Settings(levels=True))
        engine.on_bar(bar(0, 100))
        engine.on_bar(bar(1, 100))
        self.assertIsNotNone(engine.position)
        engine.warming = True
        recovered = engine.on_bar(bar(2, 100, h=120, low=80))
        self.assertFalse(kinds(recovered, "order"))
        self.assertIsNotNone(engine.position)
        self.assertIsNone(engine.pending)
        engine.warming = False
        resumed = engine.on_bar(bar(3, 105))
        trade = kinds(resumed, "trade")[0]
        self.assertEqual((trade["exit_reason"], trade["exit_raw"], trade["exit_time"]),
                         ("lacuna", 105, T0 + 180))

    def test_future_bars_do_not_change_past_events(self):
        bars = random_walk(300, seed=11)
        settings = Settings(stop_k=1, target_k=1)
        full = run(Engine(MovingAverageModel(5, 20), settings), bars)
        engine = Engine(MovingAverageModel(5, 20), settings)
        prefix = run(engine, bars[:150])
        self.assertEqual(full[:len(prefix)], prefix)
        self.assertTrue(kinds(prefix, "trade"))

    def test_review_waits_thirty_minutes_after_exit(self):
        engine = Engine(Scripted({T0: LONG}), Settings(horizon_minutes=2, **PLAIN))
        # Saída no fechamento do candle 2 (T0+180); revisão devida no fechamento do candle 32.
        events = run(engine, [bar(i, 100 + i) for i in range(32)])
        self.assertFalse(kinds(events, "review"))
        events = engine.on_bar(bar(32, 132))
        review = kinds(events, "review")[0]
        self.assertTrue(review["retrospective"])
        self.assertAlmostEqual(review["what_if_log_return"]["30"], math.log(132 / 101))
        self.assertNotIn("-5", review["what_if_log_return"])  # antes da entrada
        self.assertAlmostEqual(review["captured_log_return"], math.log(102 / 101))

    def test_outcome_compares_prediction_with_realized_return(self):
        signal = Signal(None, "cnn", predicted_log_return=.01, horizon_minutes=2)
        engine = Engine(Scripted({T0: signal}), Settings(**PLAIN))
        events = run(engine, [bar(0, 100), bar(1, 101), bar(2, 102)])
        outcome = kinds(events, "outcome")[0]
        self.assertAlmostEqual(outcome["realized"], math.log(102 / 100))
        self.assertAlmostEqual(outcome["error"], .01 - math.log(1.02))


class PerformanceTests(unittest.TestCase):
    def test_display_statistics_use_each_trade_fx_and_include_fx_effect(self):
        engine = Engine(Scripted({T0: LONG, T0 + 180: LONG}),
                        Settings(horizon_minutes=2, **PLAIN),
                        fx=lambda t: 5.0 if t < T0 + 120 else 6.0)
        run(engine, [bar(i, p) for i, p in enumerate([100, 110, 110, 100, 100, 100])])
        self.assertEqual(len(engine.trades), 2)
        result = performance(engine.trades, display=True)
        nets = [t["net_display"] for t in engine.trades]
        self.assertAlmostEqual(result["net_display"], engine.realized_display)
        self.assertAlmostEqual(result["mean_net_display"], sum(nets) / 2)
        self.assertGreater(engine.trades[0]["fx_effect_display"], 0)
        self.assertAlmostEqual(result["max_drawdown_display"], -nets[-1])
        self.assertAlmostEqual(result["groups"]["side:comprada"]["net_display"], sum(nets))
        expected = sum((t["fees_quote"] + t["slippage_quote"] + t["borrow_quote"])
                       * t["rate_entry"] for t in engine.trades)
        self.assertAlmostEqual(result["costs_display"], expected)

    def test_summary_metrics(self):
        base = {"fees_quote": .1, "slippage_quote": .05, "borrow_quote": 0., "ambiguous": False,
                "side": "comprada", "exit_reason": "tempo"}
        trades = [{**base, "net_quote": x, "gross_quote": x + .15} for x in (1., -.5, 2., -1.)]
        result = performance(trades, resamples=200)
        self.assertEqual(result["trades"], 4)
        self.assertAlmostEqual(result["net_quote"], 1.5)
        self.assertAlmostEqual(result["win_rate"], .5)
        self.assertAlmostEqual(result["profit_factor"], 2.)
        self.assertAlmostEqual(result["max_drawdown_quote"], 1.)
        self.assertAlmostEqual(result["costs_quote"], .6)
        low, high = result["mean_net_ci90"]
        self.assertLessEqual(low, result["mean_net_quote"])
        self.assertGreaterEqual(high, result["mean_net_quote"])
        self.assertEqual(performance([]), {"trades": 0})


if __name__ == "__main__":
    unittest.main()
