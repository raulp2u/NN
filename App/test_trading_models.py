from datetime import datetime, timezone
from importlib.util import find_spec
from pathlib import Path
import shutil
import tempfile
import unittest

from trading_engine import Bar

T0 = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())


def bars(count, start=T0):
    return [Bar(start + 60 * i, 100 + i * .1, 100.3 + i * .1, 99.8 + i * .1, 100.05 + i * .1, 1 + i % 3)
            for i in range(count)]


@unittest.skipIf(find_spec("torch") is None, "Requer requirements-torch-cpu.txt")
class NumericCNNModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from trading_models import NumericCNNModel
        cls.model = NumericCNNModel()

    def setUp(self):
        self.model.reset()

    def test_decides_on_every_complete_rolling_window(self):
        signals = [self.model.update(b) for b in bars(70, T0 + 600)]
        decided = [i for i, s in enumerate(signals) if s is not None]
        # Início às 00:10: pronta às 00:40, depois a cada minuto.
        self.assertEqual(decided, list(range(29, 70)))

    def test_gap_requires_new_complete_window(self):
        for b in bars(30):
            self.model.update(b)
        signals = [self.model.update(b) for b in bars(30, T0 + 31 * 60)]
        self.assertTrue(all(s is None for s in signals[:29]))
        self.assertIsNotNone(signals[-1])

    def test_prediction_matches_training_transform(self):
        import numpy as np
        from train_numeric import predict_cnn
        window = bars(30)
        raw = np.array([[[b.open, b.high, b.low, b.close, b.volume] for b in window]])
        x = self.model.standardized(raw)
        expected = predict_cnn(self.model.model, x[None], self.model.target_mean, self.model.target_scale)[0]
        signal = [self.model.update(b) for b in window][-1]
        self.assertAlmostEqual(signal.predicted_log_return, expected, places=12)
        self.assertEqual(len(signal.attributions), 30)
        self.assertIsNone(signal.direction)

    def test_integrated_gradients_completeness(self):
        import numpy as np
        raw = np.array([[[b.open, b.high, b.low, b.close, b.volume] for b in bars(30)]])
        x = self.model.standardized(raw)
        per_minute, _ = self.model.integrated_gradients(x)
        difference = self.model.predict(x) - self.model.predict(np.zeros_like(x))
        self.assertAlmostEqual(sum(per_minute), difference, delta=abs(difference) * .05 + 1e-7)

    def test_altered_artifact_is_rejected(self):
        from trading_models import ROOT, NumericCNNModel
        with tempfile.TemporaryDirectory() as folder:
            copy = Path(folder) / "numerico_v1"
            shutil.copytree(ROOT / "Modelos" / "numerico_v1", copy)
            config = copy / "config.json"
            config.write_bytes(config.read_bytes().replace(b"\n", b"\r\n"))
            NumericCNNModel(copy)  # mesma configuração com quebras de linha do Windows
            with config.open("a", encoding="utf-8") as stream:
                stream.write(" ")
            with self.assertRaisesRegex(ValueError, "config.json"):
                NumericCNNModel(copy)


if __name__ == "__main__":
    unittest.main()
