"""Numérico v2: derivativos causais, dataset multi-tempo, rótulos iguais ao motor, treino, calibração e adaptador."""

import csv
from datetime import date, datetime, timezone
from importlib.util import find_spec
import io
import json
import math
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

from derivatives_data import FEATURES, METRICS_DELAY, DerivativeSeries, fetch_live, parse_funding, parse_metrics
from trading_engine import Bar, Engine, Settings, Signal, first_touch, net_fraction

T0 = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
HAS_NUMERIC = all(find_spec(name) for name in ("numpy", "polars", "torch"))


def make_synthetic(folder, days=12, seed=0, gap=(5000, 5040)):
    """Histórico de minutos com uma lacuna, manifesto com divisões e derivativos parciais."""
    import numpy as np
    from bitcoin_data import sha256
    rng = np.random.default_rng(seed)
    data, derivatives = folder / "bitcoin", folder / "derivatives"
    data.mkdir(parents=True)
    derivatives.mkdir()
    n = days * 1440
    closes = 40000 * np.exp(np.cumsum(rng.normal(0, 8e-4, n)))
    stamp = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with (data / "btc_usdt_1m.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        previous = closes[0]
        for i in range(n):
            if gap[0] <= i < gap[1]:
                previous = closes[i]
                continue
            o, c = previous, closes[i]
            writer.writerow([stamp(T0 + 60 * i), o, max(o, c) * (1 + abs(rng.normal(0, 3e-4))),
                             min(o, c) * (1 - abs(rng.normal(0, 3e-4))), c, rng.uniform(1, 50)])
            previous = c
    day = lambda d: datetime.fromtimestamp(T0 + d * 86400, timezone.utc).isoformat().replace("+00:00", "Z")
    a, b = int(days * .6), int(days * .8)
    manifest = {"quality": {"products": [{"path": "btc_usdt_1m.csv", "sha256": sha256(data / "btc_usdt_1m.csv")}],
                            "split_boundaries": {"train": {"first_start_utc": day(0), "last_available_at_utc": day(a)},
                                                 "validation": {"first_start_utc": day(a), "last_available_at_utc": day(b)},
                                                 "test": {"first_start_utc": day(b), "last_available_at_utc": day(days)}}}}
    (data / "manifest.json").write_text(json.dumps(manifest))
    with (derivatives / "funding.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time", "rate"])
        writer.writerows([T0 + k * 28800, 1e-4] for k in range(days * 3))
    with (derivatives / "metrics.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time", "open_interest", "taker_ratio"])
        writer.writerows([T0 + k * 300, 8e4 * math.exp(k * 1e-4), 1.1] for k in range(days // 3 * 288, days * 288))
    return data, derivatives


class DerivativesTests(unittest.TestCase):
    def series(self):
        series = DerivativeSeries()
        for k in range(0, 4):
            series.add_funding(T0 + k * 28800, 1e-4 * (k + 1))
        for k in range(0, 400):
            series.add_metrics(T0 + k * 300, 1000 * math.exp(k / 100), 1.25)
        return series

    def test_metrics_need_delay_and_lags(self):
        series = self.series()
        moment = T0 + 24 * 3600 + 900
        values = dict(zip(FEATURES, series.features(moment)))
        self.assertEqual(values["has_metrics"], 1.)
        # Último registro disponível: carimbo <= moment - atraso.
        now = (moment - METRICS_DELAY - T0) // 300
        then = (moment - 3600 - METRICS_DELAY - T0) // 300
        self.assertAlmostEqual(values["oi_change_1h"], (now - then))  # 100*log(exp(k/100)) = k
        self.assertAlmostEqual(values["taker_ratio_log"], math.log(1.25))
        self.assertAlmostEqual(values["funding_bps"], 4.)
        self.assertEqual(values["has_funding"], 1.)

    def test_no_coverage_is_zero_not_event(self):
        series = self.series()
        early = dict(zip(FEATURES, series.features(T0 + 1800)))  # sem 24 h de métricas para trás
        self.assertEqual((early["has_metrics"], early["oi_change_24h"]), (0., 0.))
        late = dict(zip(FEATURES, series.features(T0 + 400 * 300 + 3600)))  # métricas paradas
        self.assertEqual(late["has_metrics"], 0.)
        stale = dict(zip(FEATURES, series.features(T0 + 3 * 28800 + 10 * 3600)))
        self.assertEqual((stale["has_funding"], stale["funding_bps"]), (0., 0.))

    def test_future_records_do_not_change_past_features(self):
        series = self.series()
        moment = T0 + 26 * 3600
        before = series.features(moment)
        series.add_metrics(T0 + 400 * 300, 1e9, 9.)
        series.add_funding(T0 + 10 * 28800, .5)
        self.assertEqual(before, series.features(moment))

    def test_parsers_check_headers(self):
        funding = "calc_time,funding_interval_hours,last_funding_rate\n1704067200000,8,0.0001\n"
        self.assertEqual(list(parse_funding(io.StringIO(funding))), [(1704067200, 1e-4)])
        with self.assertRaises(ValueError):
            list(parse_funding(io.StringIO("a,b,c\n1,2,3\n")))
        metrics = ("create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,"
                   "sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
                   "2024-01-01 00:05:00,BTCUSDT,80000.5,3e9,1.1,1.2,1.3,0.95\n2024-01-01 00:10:00,BTCUSDT,,,,,,\n")
        self.assertEqual(list(parse_metrics(io.StringIO(metrics))), [(T0 + 300, 80000.5, .95)])

    def test_live_payload_matches_history_format(self):
        payloads = {"fundingRate": [{"fundingTime": 1704067200000, "fundingRate": "0.0001"}],
                    "openInterestHist": [{"timestamp": 1704067500000, "sumOpenInterest": "80000"}],
                    "takerlongshortRatio": [{"timestamp": 1704067500000, "buySellRatio": "0.9"},
                                            {"timestamp": 1704067800000, "buySellRatio": "1.1"}]}
        get = lambda url: next(v for k, v in payloads.items() if k in url)
        self.assertEqual(fetch_live(get), ([(T0, 1e-4)], [(T0 + 300, 80000., .9)]))

    def test_build_from_checksummed_archives(self):
        import derivatives_data
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            def archive(name, text):
                path = folder / name
                with zipfile.ZipFile(path, "w") as z:
                    z.writestr(name.replace(".zip", ".csv"), text)
                return {"key": f"x/{name}", "local": str(path), "sha256": "0" * 64, "url": "u"}
            files = {"funding": archive("BTCUSDT-fundingRate-2024-01.zip",
                                        "calc_time,funding_interval_hours,last_funding_rate\n1704067200000,8,0.0001\n"),
                     "metrics": archive("BTCUSDT-metrics-2024-01-01.zip",
                                        "create_time,sum_open_interest,sum_taker_long_short_vol_ratio\n2024-01-01 00:05:00,1,1\n")}
            with mock.patch.object(derivatives_data, "download", lambda item, raw: item):
                manifest = derivatives_data.build(folder / "out", date(2024, 2, 1), [(k, v) for k, v in files.items()])
            self.assertEqual((manifest["funding_rows"], manifest["metrics_rows"]), (1, 1))
            series = DerivativeSeries.from_folder(folder / "out")
            self.assertEqual(series.funding, [1e-4])


class SharedRulesTests(unittest.TestCase):
    """Rótulos do treino, simulação de validação e motor seguem as mesmas regras."""

    def random_path(self, rng, n=30):
        price, path = 100., []
        for _ in range(n):
            o = price * math.exp(rng.gauss(0, .002))  # aberturas com salto em relação ao fechamento
            c = o * math.exp(rng.gauss(0, .003))
            path.append((o, max(o, c) * math.exp(abs(rng.gauss(0, .002))), min(o, c) * math.exp(-abs(rng.gauss(0, .002))), c))
            price = c
        return path

    @unittest.skipUnless(HAS_NUMERIC, "Requer numpy, polars e torch")
    def test_vectorized_labels_match_scalar(self):
        import numpy as np
        from supervised_v2 import CLASSES, first_touch_batch
        rng = random.Random(3)
        cases = [(self.random_path(rng), rng.choice([1, -1]), rng.uniform(.001, .02), rng.uniform(.001, .02))
                 for _ in range(400)]
        category, exit_raw, minutes = first_touch_batch(np.array([c[0] for c in cases]), np.array([c[1] for c in cases]),
                                                        np.array([c[2] for c in cases]), np.array([c[3] for c in cases]))
        for i, case in enumerate(cases):
            label, price, held = first_touch(*case)
            self.assertEqual((CLASSES[category[i]], minutes[i]), (label, held))
            self.assertAlmostEqual(exit_raw[i], price, places=9)  # np.exp e math.exp diferem no último bit
        self.assertGreater(len(set(category.tolist())), 2)

    def test_engine_trades_follow_first_touch(self):
        rng = random.Random(7)
        for trial in range(60):
            side, stop, target = rng.choice([1, -1]), rng.uniform(.002, .02), rng.uniform(.002, .02)
            path = self.random_path(rng, 31)

            class Once:
                window, level_triggered, done = 1, False, False
                def reset(self): pass
                def update(self, bar):
                    if self.done:
                        return None
                    self.done = True
                    return Signal(side, "teste", stop_distance=stop, target_distance=target)

            engine = Engine(Once(), Settings(horizon_minutes=30))
            for i, (o, h, low, c) in enumerate([(100, 100, 100, 100)] + path):
                engine.on_bar(Bar(T0 + 60 * i, o, h, low, c, 1.))
            trade = engine.trades[0]
            label, price, held = first_touch(path[:30], side, stop, target)
            self.assertEqual((trade["exit_reason"], trade["exit_raw"], trade["minutes"]), (label, price, held), trial)
            expected = net_fraction(side, path[0][0], price, held, 10, 5, .1)
            self.assertAlmostEqual(trade["net_quote"] / trade["stake_quote"], expected, places=12)


class ExpectedValuePolicyTests(unittest.TestCase):
    def run_engine(self, sides, margin, allow_short=True):
        class Fixed:
            window, level_triggered = 1, False
            def reset(self): pass
            def update(self, bar):
                return Signal(None, "fixo", predicted_log_return=0., horizon_minutes=30, sides=sides, ev_margin=margin,
                              interval={"low": -.01, "high": .01, "coverage": .9})
        engine = Engine(Fixed(), Settings(allow_short=allow_short))
        events = engine.on_bar(Bar(T0, 100, 100, 100, 100, 1)) + engine.on_bar(Bar(T0 + 60, 100, 100, 100, 100, 1))
        return engine, [e for e in events if e["kind"] == "decision"][0], events

    def side(self, p_target, p_stop, stop=.004, target=.01):
        return {"p_target": p_target, "p_stop": p_stop, "p_time": 1 - p_target - p_stop,
                "stop_distance": stop, "target_distance": target, "time_return": 0.}

    def test_enters_best_side_with_predicted_levels(self):
        engine, decision, events = self.run_engine({1: self.side(.2, .7), -1: self.side(.7, .2)}, 0.)
        self.assertEqual(decision["action"], "VENDER A DESCOBERTO")
        self.assertEqual(decision["evaluated_side"], -1)
        expected = .7 * net_fraction(-1, 1, math.exp(-.01), 15, 10, 5, .1) + .2 * net_fraction(-1, 1, math.exp(.004), 15, 10, 5, .1) \
            + .1 * net_fraction(-1, 1, 1., 30, 10, 5, .1)
        self.assertAlmostEqual(decision["expected_values"][-1], expected, places=12)
        order = next(e for e in events if e["kind"] == "order")
        self.assertEqual(order["levels_source"], "modelo")
        self.assertAlmostEqual(order["stop"], 100 * math.exp(.004))
        self.assertAlmostEqual(order["target"], 100 * math.exp(-.01))

    def test_margin_and_no_trade_policy(self):
        _, decision, _ = self.run_engine({1: self.side(.7, .2), -1: self.side(.1, .8)}, .05)
        self.assertEqual(decision["action"], "AGUARDAR")
        _, decision, _ = self.run_engine({1: self.side(.9, .05), -1: self.side(.1, .8)}, None)
        self.assertEqual(decision["action"], "AGUARDAR")
        self.assertIn("não opera", decision["reason"])

    def test_short_disabled_still_shows_values(self):
        _, decision, _ = self.run_engine({1: self.side(.2, .7), -1: self.side(.7, .2)}, 0., allow_short=False)
        self.assertEqual((decision["action"], decision["evaluated_side"]), ("AGUARDAR", 1))
        self.assertIn(-1, decision["expected_values"])

    def test_outcome_records_category_and_interval(self):
        class Fixed:
            window, level_triggered = 1, False
            def reset(self): pass
            def update(self, bar):
                return Signal(None, "fixo", predicted_log_return=0., horizon_minutes=30, ev_margin=1.,
                              sides={1: {"p_target": .5, "p_stop": .3, "p_time": .2, "stop_distance": .5,
                                         "target_distance": .002, "time_return": 0.}},
                              interval={"low": -.001, "high": .001, "coverage": .9})
        engine = Engine(Fixed(), Settings())
        events = []
        for i in range(40):
            price = 100 * (1.003 if i == 5 else 1.)
            events += engine.on_bar(Bar(T0 + 60 * i, 100, max(100, price), 100, 100, 1))
        first = next(e for e in events if e["kind"] == "outcome")
        self.assertEqual((first["category"], first["side"], first["inside_interval"]), ("alvo", 1, True))
        self.assertEqual(set(first["probabilities"]), {"p_target", "p_stop", "p_time"})


@unittest.skipUnless(HAS_NUMERIC, "Requer numpy, polars e torch")
class DatasetV2Tests(unittest.TestCase):
    def test_views_are_causal_and_aligned(self):
        import numpy as np
        from supervised_v2 import Views, aggregate, run_lengths
        np.testing.assert_array_equal(run_lengths(np.array([1, 1, 0, 1, 1, 1], bool)), [1, 2, 0, 1, 2, 3])
        times = T0 + 60 * np.arange(3 * 1440)
        values = np.column_stack([np.arange(len(times)) + 100.] * 4 + [np.ones(len(times))])
        values[:, 1] += .5
        values[:, 2] -= .5
        views = Views(times, values)
        index = views.index(times[[3000]])
        raw = views.inputs(index)
        self.assertEqual({k: v.shape for k, v in raw.items()}, {"m1": (1, 30, 5), "m5": (1, 48, 5), "h1": (1, 48, 5)})
        # Decisão após o minuto 3000 (fechado às 3001): último candle de 5 min completo = minutos 2995-2999.
        self.assertEqual(raw["m5"][0, -1, 0], 100 + 2995)
        self.assertEqual(raw["h1"][0, -1, 3], 100 + 2999)  # hora 2940-2999, a última encerrada
        self.assertEqual(aggregate(values[:10].copy(), 5)[1, 4], 5.)
        changed = values.copy()
        changed[3001:, :4] *= 3
        later = Views(times, changed).inputs(index)
        for key in raw:
            np.testing.assert_array_equal(raw[key], later[key])

    def test_gap_blocks_windows_and_labels(self):
        import numpy as np
        from supervised_v2 import Views
        times = T0 + 60 * np.r_[np.arange(0, 4000), np.arange(4010, 7000)]
        values = np.column_stack([np.full(len(times), 100.)] * 4 + [np.ones(len(times))])
        views = Views(times, values)
        index = views.index(T0 + 60 * np.array([3970, 3990, 4100, 6000]))
        # 3970: rótulo cruza a lacuna; 3990: idem; 4100: 1 min ok, mas 1 h incompleta; 6000: h1 ainda inclui a lacuna.
        self.assertEqual(views.eligible(index, 30).tolist(), [False, False, False, False])
        later = Views(np.r_[times, T0 + 60 * np.arange(7000, 7000 + 3 * 1440)],
                      np.vstack([values, values[:3 * 1440]]))
        self.assertTrue(later.eligible(later.index([T0 + 60 * 9000]), 30)[0])

    def test_build_respects_split_boundaries(self):
        import numpy as np
        from supervised_v2 import build
        with tempfile.TemporaryDirectory() as folder:
            data, derivatives = make_synthetic(Path(folder))
            summary = build(data, derivatives, Path(folder) / "sup", stride=15)
            boundaries = summary["original_boundaries"]
            for name in ("train", "validation", "test"):
                split = np.load(Path(folder) / "sup" / f"{name}.npz")
                last = datetime.fromisoformat(boundaries[name]["last_available_at_utc"].replace("Z", "+00:00")).timestamp()
                self.assertTrue(np.all(split["available"] + 1800 <= last))
                self.assertEqual(split["derivatives"].shape[1], len(FEATURES))
            self.assertLess(summary["derivative_coverage"]["train"]["metrics"], 1.)
            with self.assertRaisesRegex(ValueError, "já existe"):
                build(data, derivatives, Path(folder) / "sup", stride=15)


@unittest.skipUnless(HAS_NUMERIC, "Requer numpy, polars e torch")
class TrainingV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from supervised_v2 import build
        import train_v2
        cls.folder = tempfile.TemporaryDirectory()
        root = Path(cls.folder.name)
        data, cls.derivatives = make_synthetic(root)
        cls.data = data
        build(data, cls.derivatives, root / "sup", stride=15)
        cls.model_dir = root / "model"
        argv = ["train_v2.py", "--data", str(root / "sup"), "--out", str(cls.model_dir), "--results", str(root / "res"),
                "--epochs", "2", "--samples-per-epoch", "1500", "--batch-size", "256"]
        with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
            train_v2.main()
        cls.report = json.loads((cls.model_dir / "report.json").read_text(encoding="utf-8"))
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_report_is_complete_and_calibrated_on_validation_only(self):
        report = self.report
        calibration = report["calibration"]
        self.assertGreater(calibration["temperature"], 0)
        self.assertGreaterEqual(calibration["conformal_delta"], 0)
        self.assertIn(calibration["tau_stop"], (.25, .5, .75))
        for part in ("validation_evaluation_half", "test_retrospective"):
            self.assertIn("coverage_90", report[part]["interval"])
            self.assertIn("ece", report[part]["outcome_calibration"])
        self.assertTrue((self.root / "res" / "calibration_candidates.json").exists())

    def test_temperature_and_reliability(self):
        import numpy as np
        from train_v2 import fit_temperature, reliability, temper
        rng = np.random.default_rng(0)
        logits = rng.normal(0, 1, (5000, 3))
        true = np.exp(logits) / np.exp(logits).sum(1, keepdims=True)
        labels = np.array([rng.choice(3, p=p) for p in true])
        overconfident = temper(true, .5)  # temperatura 0,5 deixa as probabilidades extremas demais
        self.assertAlmostEqual(fit_temperature(overconfident, labels), 2., delta=.35)
        self.assertLess(reliability(true, labels)["ece"], reliability(overconfident, labels)["ece"])

    def adapter(self, **options):
        from trading_models import NumericV2Model
        return NumericV2Model(self.model_dir, derivatives=DerivativeSeries.from_folder(self.derivatives), **options)

    def test_live_adapter_matches_batch_prediction(self):
        import numpy as np
        import train_v2
        from supervised_v2 import Views
        manifest, views, splits = train_v2.load(self.root / "sup")
        model = self.adapter()
        scalers = model.scalers
        batches = train_v2.Batches(views, splits["validation"], scalers)
        batch = train_v2.predict(model.model, batches, np.array([5]))
        open_time = views.t0 + 60 * int(batches.index[5])
        minutes = np.load(self.root / "sup" / "minutes.npz")
        keep = (minutes["times"] > open_time - 60 * model.window) & (minutes["times"] <= open_time)
        for t, row in zip(minutes["times"][keep], minutes["ohlcv"][keep]):
            model.observe(Bar(int(t), *map(float, row)))
        live = model.prediction()
        np.testing.assert_allclose(live["returns"], batch["returns"], rtol=1e-5, atol=1e-9)
        np.testing.assert_allclose(live["up"], batch["up"], rtol=1e-5, atol=1e-9)

    def test_engine_runs_with_adapter(self):
        from trading_sources import read_history
        model = self.adapter(ev_margin=-1.)  # margem manual negativa força entradas para exercitar o fluxo
        engine = Engine(model, Settings())
        start = T0 + 9 * 86400
        events = []
        for bar in read_history(self.data / "btc_usdt_1m.csv", start - model.window * 60, start + 180 * 60):
            engine.warming = bar.open_time < start
            events += engine.on_bar(bar)
        decisions = [e for e in events if e["kind"] == "decision"]
        self.assertTrue(decisions)
        self.assertEqual(decisions[0]["time"], start)  # janela carregada no aquecimento: decide no primeiro minuto
        last = decisions[-1]
        self.assertLess(last["interval"]["low"], last["predicted_log_return"])
        self.assertLess(last["predicted_log_return"], last["interval"]["high"])
        for side in last["sides"].values():
            self.assertAlmostEqual(side["p_target"] + side["p_stop"] + side["p_time"], 1., places=5)
        self.assertTrue(any(e["kind"] == "trade" and e["levels_source"] == "modelo" for e in events))
        self.assertTrue(any(e["kind"] == "outcome" and "category" in e for e in events))
        json.dumps(events, allow_nan=False)

    def test_altered_artifact_is_rejected(self):
        import shutil
        copy = self.root / "altered"
        shutil.copytree(self.model_dir, copy)
        (copy / "calibration.json").write_text("{}", encoding="utf-8")
        from trading_models import NumericV2Model
        with self.assertRaisesRegex(ValueError, "calibration.json"):
            NumericV2Model(copy)
        with self.assertRaisesRegex(FileNotFoundError, "train_v2"):
            NumericV2Model(self.root / "inexistente")


if __name__ == "__main__":
    unittest.main()
