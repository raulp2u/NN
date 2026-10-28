"""Adaptadores de modelo para o motor: médias móveis do quantlab e CNN numérica v1."""

from collections import deque
import hashlib
import json
from pathlib import Path

from trading_engine import MINUTE, Signal

ROOT = Path(__file__).resolve().parent.parent


class MovingAverageModel:
    """Mesma aritmética de quantlab.targets, incremental. Visão de estado a cada minuto."""
    level_triggered = True

    def __init__(self, fast=5, slow=20):
        if not isinstance(fast, int) or not isinstance(slow, int) or not 1 <= fast < slow:
            raise ValueError("Janelas inteiras devem satisfazer 1 <= fast < slow")
        self.fast, self.slow = fast, slow
        self.window = slow
        self.name = f"medias_moveis_{fast}_{slow}"
        self.version = self.name
        self.description = f"Médias móveis {fast}/{slow} de quantlab.py; não é modelo aprendido"
        self.reset()

    def reset(self):
        self.short, self.long = deque(), deque()
        self.short_sum = self.long_sum = 0.0

    def update(self, bar):
        self.short.append(bar.close)
        self.long.append(bar.close)
        self.short_sum += bar.close
        self.long_sum += bar.close
        if len(self.short) > self.fast:
            self.short_sum -= self.short.popleft()
        if len(self.long) > self.slow:
            self.long_sum -= self.long.popleft()
        if len(self.long) < self.slow:
            return None
        fast, slow = self.short_sum / self.fast, self.long_sum / self.slow
        direction = 1 if fast > slow else -1
        return Signal(direction, f"média {self.fast} {'acima' if direction == 1 else 'abaixo'} da média {self.slow}",
                      details={"fast_mean": fast, "slow_mean": slow})


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def matches(path, expected):
    """Binários exigem bytes idênticos; JSON aceita LF ou CRLF (o Git normaliza quebras de linha)."""
    data = Path(path).read_bytes()
    variants = [data]
    if Path(path).suffix == ".json":
        lf = data.replace(b"\r\n", b"\n")
        variants += [lf, lf.replace(b"\n", b"\r\n")]
    return any(hashlib.sha256(v).hexdigest() == expected for v in variants)


class NumericCNNModel:
    """Checkpoint congelado, aplicado a cada janela móvel de 30 minutos completos."""
    level_triggered = False
    window = 30
    horizon = 30

    def __init__(self, folder=ROOT / "Modelos" / "numerico_v1", report=ROOT / "Relatorios" / "numerico_v1" / "report.json",
                 attribution_steps=32):
        import numpy as np
        import torch
        from supervised_data import features
        from train_numeric import NumericCNN
        folder = Path(folder)
        expected = json.loads(Path(report).read_text(encoding="utf-8"))["artifacts"]
        for name in ("cnn.pt", "scalers.npz", "config.json"):
            if not matches(folder / name, expected[name]):
                raise ValueError(f"Artefato diferente do relatório de treinamento: {name}")
        config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
        scalers = np.load(folder / "scalers.npz")
        self.np, self.torch, self.features = np, torch, features
        self.mean = scalers["feature_mean"].astype(np.float64)[:, None]
        self.scale = scalers["feature_scale"].astype(np.float64)[:, None]
        self.target_mean = float(scalers["target_mean"])
        self.target_scale = float(scalers["target_scale"])
        self.model = NumericCNN()
        self.model.load_state_dict(torch.load(folder / "cnn.pt", weights_only=True, map_location="cpu"))
        self.model.eval()
        self.steps = attribution_steps
        self.channels = config["channels"]
        self.version = sha256(folder / "cnn.pt")[:12]
        self.name = "numerico_v1"
        self.description = ("CNN 1D numérica v1: prevê o retorno log de 30 minutos. Não prevê stop, alvo nem "
                            "probabilidades; confiança calibrada indisponível")
        self.reset()

    def reset(self):
        self.bars = deque(maxlen=self.window)

    def standardized(self, raw):
        x = self.features(raw)[0].astype(self.np.float64)
        return ((x - self.mean) / self.scale).astype(self.np.float32)

    def predict(self, x):
        with self.torch.no_grad():
            output = self.model(self.torch.from_numpy(x[None]))
        return float(output[0]) * self.target_scale + self.target_mean

    def integrated_gradients(self, x):
        """Atribuição por minuto (soma dos canais), em retorno log, contra a média do treino."""
        torch = self.torch
        inputs = torch.from_numpy(x)
        alphas = (torch.arange(self.steps, dtype=torch.float32) + .5) / self.steps
        path = (alphas[:, None, None] * inputs[None]).requires_grad_(True)
        self.model(path).sum().backward()
        attribution = (inputs * path.grad.mean(0)).detach().numpy().astype(self.np.float64) * self.target_scale
        return attribution.sum(0).tolist(), attribution

    def update(self, bar):
        if self.bars and bar.open_time != self.bars[-1].open_time + MINUTE:
            self.reset()
        self.bars.append(bar)
        if len(self.bars) < self.window:
            return None
        raw = self.np.array([[[b.open, b.high, b.low, b.close, b.volume] for b in self.bars]], dtype=self.np.float64)
        x = self.standardized(raw)
        predicted = self.predict(x)
        per_minute, _ = self.integrated_gradients(x)
        return Signal(None, "CNN numérica v1", predicted_log_return=predicted, horizon_minutes=self.horizon,
                      attributions=per_minute,
                      details={"baseline_prediction": self.target_mean,
                               "attribution": "Integrated Gradients contra a média do treino; influência no modelo, não causa no mercado"})


MODELS = {"cnn": NumericCNNModel, "medias": MovingAverageModel}
