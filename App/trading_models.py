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


class NumericV2Model:
    """Numérico v2: faixa de retorno, stop e alvo das excursões e probabilidades calibradas de desfecho.

    Decide a cada minuto com 30 candles de 1 min, 48 de 5 min e 48 de 1 h encerrados, mais derivativos."""
    level_triggered = False
    horizon = 30
    window = 49 * 60  # 48 horas completas na grade do relógio, qualquer que seja o minuto atual
    ready = 48 * 60   # com menos candles, as 48 horas fechadas nunca estão completas

    def __init__(self, folder=ROOT / "Modelos" / "numerico_v2", derivatives=None, ev_margin=None, attribution_steps=16):
        import numpy as np
        import torch
        from derivatives_data import FEATURES, DerivativeSeries
        import supervised_v2
        import train_v2
        folder = Path(folder)
        if not (folder / "report.json").exists():
            raise FileNotFoundError(f"Modelo v2 não encontrado em {folder}. Treine com App/supervised_v2.py e "
                                    "App/train_v2.py (ver App/INTERFACE.md).")
        expected = json.loads((folder / "report.json").read_text(encoding="utf-8"))["artifacts"]
        for name in ("model.pt", "scalers.npz", "config.json", "calibration.json"):
            if not matches(folder / name, expected[name]):
                raise ValueError(f"Artefato diferente do relatório de treinamento: {name}")
        self.np, self.torch, self.v2, self.train = np, torch, supervised_v2, train_v2
        self.derivative_names = FEATURES
        self.scalers = {key: value for key, value in np.load(folder / "scalers.npz").items()}
        self.calibration = json.loads((folder / "calibration.json").read_text(encoding="utf-8"))
        self.model = train_v2.MultiHeadNet(len(self.scalers["context_mean"]))
        self.model.load_state_dict(torch.load(folder / "model.pt", weights_only=True, map_location="cpu"))
        self.model.eval()
        self.derivatives = derivatives if derivatives is not None else DerivativeSeries()
        calibrated = self.calibration["ev_margin"]
        self.manual_margin = ev_margin is not None
        self.ev_margin = ev_margin if ev_margin is not None else calibrated
        self.steps = attribution_steps
        self.version = sha256(folder / "model.pt")[:12]
        self.name = "numerico_v2"
        margin = ("sem margem lucrativa na calibração: não opera" if self.ev_margin is None
                  else f"margem {100 * self.ev_margin:.2f}%{' (manual)' if self.manual_margin else ''}")
        self.description = ("CNN multi-tempo v2: faixa de 90% do retorno, stop e alvo previstos, probabilidades "
                            f"calibradas de alvo, stop ou tempo e entrada por valor esperado; {margin}")
        self.reset()

    def reset(self):
        self.bars = deque(maxlen=self.window)

    def observe(self, bar):
        """Aquecimento: guarda o candle sem inferência."""
        if self.bars and bar.open_time != self.bars[-1].open_time + MINUTE:
            self.reset()
        self.bars.append(bar)

    def prediction(self):
        """Saída do modelo para o último candle, ou None se as janelas não estão completas."""
        np = self.np
        times = np.array([b.open_time for b in self.bars])
        views = self.v2.Views(times, [[b.open, b.high, b.low, b.close, b.volume] for b in self.bars])
        index = views.index(times[-1:])
        if not views.eligible(index)[0]:
            return None
        raw = views.inputs(index)
        sigma = np.maximum(self.v2.recent_volatility(raw["m1"]), self.train.VOL_FLOOR)
        context = np.array([self.derivatives.features(int(times[-1]) + MINUTE)], dtype=np.float64)
        x, context_tensor = self.train.prepare(raw, sigma, context, self.scalers)
        with self.torch.no_grad():
            h, out = self.model(x, context_tensor)
        result = {"h": h, "sigma": sigma, "context": context[0], "x": x, "context_tensor": context_tensor}
        result["returns"] = out["returns"].numpy() * float(self.scalers["return_scale"])
        result["up"] = out["up"].numpy() * float(self.scalers["excursion_scale"])
        result["down"] = out["down"].numpy() * float(self.scalers["excursion_scale"])
        return result

    def integrated_gradients(self, prediction):
        """Atribuição por minuto da visão de 1 min na mediana prevista, contra a média do treino."""
        torch = self.torch
        inputs = prediction["x"]["m1"][0]
        alphas = (torch.arange(self.steps, dtype=torch.float32) + .5) / self.steps
        path = (alphas[:, None, None] * inputs[None]).requires_grad_(True)
        others = {key: value.expand(self.steps, -1, -1) for key, value in prediction["x"].items() if key != "m1"}
        _, out = self.model({"m1": path, **others}, prediction["context_tensor"].expand(self.steps, -1))
        out["returns"][:, self.train.QUANTILES.index(.5)].sum().backward()
        attribution = (inputs * path.grad.mean(0)).detach().numpy() * float(self.scalers["return_scale"])
        return attribution.sum(0).tolist()

    def update(self, bar):
        self.observe(bar)
        if len(self.bars) < self.ready:
            return None
        prediction = self.prediction()
        if prediction is None:
            return None
        c = self.calibration
        q = prediction["returns"][0]
        median = float(q[self.train.QUANTILES.index(.5)])
        sides = {}
        for side in (1, -1):
            stop, target = self.train.side_levels(prediction, side, c["tau_stop"], c["tau_target"])
            probabilities, time_return = self.train.outcome(self.model, prediction, side, stop, target,
                                                            self.scalers, c["temperature"])
            sides[side] = {"p_target": float(probabilities[0, 0]), "p_stop": float(probabilities[0, 1]),
                           "p_time": float(probabilities[0, 2]), "stop_distance": float(stop[0]),
                           "target_distance": float(target[0]), "time_return": float(time_return[0])}
        return Signal(None, "CNN multi-tempo v2", predicted_log_return=median, horizon_minutes=self.horizon,
                      attributions=self.integrated_gradients(prediction),
                      interval={"low": float(q[0] - c["conformal_delta"]), "high": float(q[-1] + c["conformal_delta"]),
                                "coverage": c["coverage_target"],
                                "quantiles": {str(k): float(v) for k, v in zip(self.train.QUANTILES, q)}},
                      sides=sides, ev_margin=self.ev_margin,
                      details={"derivatives": dict(zip(self.derivative_names, map(float, prediction["context"]))),
                               "volatility_used": float(prediction["sigma"][0]),
                               "temperature": c["temperature"], "manual_margin": self.manual_margin,
                               "attribution": "Integrated Gradients na mediana, visão de 1 min; influência no modelo, não causa no mercado"})

MODELS = {"cnn": NumericCNNModel, "medias": MovingAverageModel, "v2": NumericV2Model}
