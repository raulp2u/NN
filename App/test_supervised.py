import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import polars as pl
import torch

from bitcoin_data import sha256
from supervised_data import build, features, label_masks
from train_numeric import NumericCNN, cost_hurdle, normalize, simulated_policy


def price_window():
    o = 100 + .1*np.arange(30)
    return np.stack([o, o+.2, o-.1, o+.05, np.ones(30)], axis=1)[None, :, :]


class SupervisedDataTests(unittest.TestCase):
    def test_feature_values_and_price_scale_invariance(self):
        raw = price_window()
        x = features(raw)
        self.assertEqual(x.shape, (1, 8, 30))
        self.assertAlmostEqual(float(x[0, 0, 0]), 0.)
        self.assertAlmostEqual(float(x[0, 3, 29]), 100*np.log(102.95/100), places=5)
        self.assertEqual(float(x[0, 5, 0]), 0.)
        self.assertEqual(float(x[0, 6, 1]), 0.)
        changed = raw.copy()
        changed[:, :, :4] *= 10
        np.testing.assert_allclose(x, features(changed), atol=1e-6)

    def test_no_future_examples_affect_existing_inputs(self):
        past = price_window()
        future = past.copy()
        future[:, :, :4] *= 20
        np.testing.assert_array_equal(features(past), features(np.concatenate([past, future]))[:1])

    def test_gap_boundary_and_unavailable_future(self):
        starts = np.array([0, 1800, 3600, 7200, 9000, 10800])
        accepted, reasons = label_masks(starts, starts+1800,
                                       ["train", "train", "validation", "validation", "test", "test"],
                                       {"train": 3600, "validation": 9000, "test": 12600})
        self.assertEqual(reasons.tolist(), ["accepted", "split_boundary", "future_gap", "split_boundary", "accepted", "no_future"])
        self.assertEqual(np.flatnonzero(accepted).tolist(), [0, 4])

    def test_real_contract_fixture_label_and_parquet(self):
        from datetime import datetime, timedelta, timezone
        with tempfile.TemporaryDirectory() as folder:
            data, output = Path(folder) / "source", Path(folder) / "output"
            data.mkdir()
            start = datetime(2020, 1, 1, tzinfo=timezone.utc)
            rows, splits = [], []
            for i in range(6):
                row = {"window_id": i, "start_utc": (start+timedelta(minutes=30*i)).isoformat(),
                       "available_at_utc": (start+timedelta(minutes=30*(i+1))).isoformat(), "samples": 30}
                for minute in range(30):
                    price = 100+.1*(30*i+minute)
                    for field, value in zip(("open", "high", "low", "close", "volume"), (price, price+.2, price-.1, price+.05, 1.)):
                        row[f"{field}_{minute:02}"] = value
                rows.append(row)
                splits.append({key: row[key] for key in ("window_id", "start_utc", "available_at_utc")})
                splits[-1]["split"] = ("train", "validation", "test")[i//2]
            pl.DataFrame(rows).write_csv(data / "snapshots_30m.csv")
            pl.DataFrame(splits).write_csv(data / "splits.csv")
            products = [{"path": name, "sha256": sha256(data / name)} for name in ("snapshots_30m.csv", "splits.csv")]
            boundaries = {name: {"first_start_utc": rows[i]["start_utc"], "last_available_at_utc": rows[i+1]["available_at_utc"]}
                          for name, i in (("train", 0), ("validation", 2), ("test", 4))}
            (data / "manifest.json").write_text(json.dumps({"quality": {"windows": 6, "products": products, "split_boundaries": boundaries}}), encoding="utf-8")
            summary = build(data, output)
            self.assertEqual(summary["counts"], {"train": 1, "validation": 1, "test": 1})
            train = pl.read_parquet(output / "train.parquet")
            self.assertAlmostEqual(train["target_log_return"][0], np.log(105.95/102.95))
            self.assertEqual(train["execution_open_future"][0], 103.)
            self.assertEqual(train["features"].to_numpy().shape, (1, 240))
            with self.assertRaises(ValueError):
                build(data, output)


class NumericTrainingTests(unittest.TestCase):
    def test_scaler_fits_train_only(self):
        train = np.ones((2, 8, 30), dtype=np.float32)
        validation = np.full((1, 8, 30), 999., dtype=np.float32)
        scaler, (scaled_train, scaled_validation) = normalize(train, validation)
        np.testing.assert_array_equal(scaler.mean_, np.ones(8))
        self.assertTrue((scaled_train == 0).all())
        self.assertTrue((scaled_validation == 998).all())

    def test_checkpoint_roundtrip_preserves_predictions(self):
        torch.manual_seed(42)
        model = NumericCNN().eval()
        x = torch.randn(2, 8, 30)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cnn.pt"
            torch.save(model.state_dict(), path)
            restored = NumericCNN().eval()
            restored.load_state_dict(torch.load(path, weights_only=True))
            torch.testing.assert_close(model(x), restored(x), rtol=0, atol=0)

    def test_round_trip_cost_barrier_is_exact(self):
        multiplier = np.exp(cost_hurdle())
        frame = pl.DataFrame({"execution_open_future": [100.], "exit_close_future": [100.*multiplier]})
        result, _ = simulated_policy(frame, np.array([1.]))
        self.assertAlmostEqual(result["net_return"], 0., places=12)
        self.assertEqual(result["round_trips"], 1)

    def test_no_trade_below_cost_and_no_free_flat_round_trip(self):
        frame = pl.DataFrame({"execution_open_future": [100., 100.], "exit_close_future": [100., 100.]})
        flat, _ = simulated_policy(frame, np.zeros(2))
        traded, _ = simulated_policy(frame, np.ones(2))
        self.assertEqual(flat["round_trips"], 0)
        self.assertEqual(flat["net_return"], 0.)
        expected = ((.9995*.999)/(1.0005*1.001))**2-1
        self.assertAlmostEqual(traded["net_return"], expected)


if __name__ == "__main__":
    unittest.main()
