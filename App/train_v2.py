"""Numérico v2: faixa de retorno, excursões, desfecho stop/alvo calibrado e política por valor esperado.

Validação dividida em duas metades cronológicas: a primeira escolhe a época, a temperatura, o ajuste
conformal, os quantis de stop/alvo e a margem; a segunda avalia tudo congelado. O teste é aberto uma
única vez, no final. Pequenos artefatos vão para Modelos/numerico_v2; previsões, para App/results.
"""

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import math
from pathlib import Path
import random
import time

import numpy as np
import torch
from torch import nn

from bitcoin_data import sha256
from supervised_v2 import CLASSES, HORIZON, SCALES, Views, first_touch_batch, model_inputs, recent_volatility, targets
from trading_engine import net_fraction

ROOT = Path(__file__).resolve().parent.parent
QUANTILES = (.05, .25, .5, .75, .95)
LEVEL_QUANTILES = (.25, .5, .75)
LEVEL_RANGE = (.3, 4.)  # níveis sorteados em desvios da volatilidade recente
MARGINS = (0., .0005, .001, .002, .003)
MIN_TRADES = 30
COVERAGE = .9
LOSS_WEIGHTS = {"return": 1., "excursion": 1., "outcome": 1., "time_return": .5}
COSTS = {"fee_bps": 10., "slippage_bps": 5., "borrow_bps_per_hour": .1}
VOL_FLOOR = 1e-4


class Encoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.Sequential(nn.Conv1d(8, 16, 3, padding=1), nn.GELU(), nn.Conv1d(16, 32, 3, padding=1), nn.GELU())

    def forward(self, x):
        h = self.layers(x)
        return torch.cat([h.mean(-1), h[:, :, -1]], dim=1)  # média da janela e estado mais recente


class Monotone(nn.Module):
    """Quantis que não se cruzam: primeiro valor livre, incrementos positivos."""

    def __init__(self, width, count):
        super().__init__()
        self.linear = nn.Linear(width, count)

    def forward(self, h):
        raw = self.linear(h)
        return torch.cat([raw[:, :1], raw[:, :1] + torch.cumsum(nn.functional.softplus(raw[:, 1:]), 1)], 1)


class MultiHeadNet(nn.Module):
    def __init__(self, context_size):
        super().__init__()
        self.encoders = nn.ModuleDict({key: Encoder() for key in SCALES})
        self.context = nn.Sequential(nn.Linear(context_size, 16), nn.GELU())
        self.trunk = nn.Sequential(nn.Linear(64 * len(SCALES) + 16, 96), nn.GELU(), nn.Dropout(.1),
                                   nn.Linear(96, 64), nn.GELU())
        self.returns = Monotone(64, len(QUANTILES))
        self.up, self.down = Monotone(64, len(LEVEL_QUANTILES)), Monotone(64, len(LEVEL_QUANTILES))
        self.outcome = nn.Sequential(nn.Linear(64 + 3, 32), nn.GELU(), nn.Linear(32, len(CLASSES) + 1))

    def forward(self, inputs, context):
        h = self.trunk(torch.cat([self.encoders[key](inputs[key]) for key in SCALES] + [self.context(context)], 1))
        return h, {"returns": self.returns(h), "up": self.up(h), "down": self.down(h)}

    def outcome_head(self, h, side, stop_sigmas, target_sigmas):
        """side ±1; níveis em desvios da volatilidade. Retorna (logits [B,3], retorno no tempo padronizado)."""
        out = self.outcome(torch.cat([h, side[:, None], torch.log(stop_sigmas)[:, None],
                                      torch.log(target_sigmas)[:, None]], 1))
        return out[:, :len(CLASSES)], out[:, len(CLASSES)]


def pinball(prediction, target, quantiles):
    q = torch.tensor(quantiles, dtype=prediction.dtype)
    error = target[:, None] - prediction
    return torch.maximum(q * error, (q - 1) * error).mean()


class Batches:
    """Monta entradas e rótulos a partir da grade de minutos, sem gravar janelas em disco."""

    def __init__(self, views, split, scalers=None):
        self.views, self.index = views, split["index"]
        self.derivatives = split["derivatives"].astype(np.float64)
        self.scalers = scalers

    def raw(self, rows):
        index = self.index[rows]
        raw = self.views.inputs(index)
        path = self.views.future(index)
        sigma = np.maximum(recent_volatility(raw["m1"]), VOL_FLOOR)
        return raw, path, sigma, self.derivatives[rows]

    def tensors(self, raw, sigma, derivatives):
        return prepare(raw, sigma, derivatives, self.scalers)


def prepare(raw, sigma, derivatives, s):
    """Entradas padronizadas do modelo; a mesma função no treino e no adaptador ao vivo."""
    x = {key: torch.from_numpy(((value - s[f"{key}_mean"][:, None]) / s[f"{key}_scale"][:, None]).astype(np.float32))
         for key, value in model_inputs(raw).items()}
    context = np.concatenate([derivatives, np.log(sigma)[:, None]], 1)
    return x, torch.from_numpy(((context - s["context_mean"]) / s["context_scale"]).astype(np.float32))


def fit_scalers(batches, rows):
    raw, path, sigma, derivatives = batches.raw(rows)
    result = {}
    for key, value in model_inputs(raw).items():
        flat = value.transpose(0, 2, 1).reshape(-1, value.shape[1])
        result[f"{key}_mean"], result[f"{key}_scale"] = flat.mean(0), flat.std(0) + 1e-8
    context = np.concatenate([derivatives, np.log(sigma)[:, None]], 1)
    result["context_mean"], result["context_scale"] = context.mean(0), context.std(0) + 1e-8
    # Indicadores de cobertura constantes no treino não podem virar divisão por zero.
    result["context_scale"][result["context_scale"] < 1e-6] = 1.
    y = targets(path, raw["m1"][:, -1, 3])
    result["return_scale"] = float(y["return"].std()) or 1.
    result["excursion_scale"] = float(np.concatenate([y["up"], y["down"]]).std()) or 1.
    return result


def sample_levels(n, generator):
    low, high = np.log(LEVEL_RANGE[0]), np.log(LEVEL_RANGE[1])
    side = generator.choice([-1., 1.], n)
    return side, np.exp(generator.uniform(low, high, n)), np.exp(generator.uniform(low, high, n))


def batch_loss(model, batches, rows, generator, training):
    s = batches.scalers
    raw, path, sigma, derivatives = batches.raw(rows)
    x, context = batches.tensors(raw, sigma, derivatives)
    y = targets(path, raw["m1"][:, -1, 3])
    side, k_stop, k_target = sample_levels(len(rows), generator)
    category, _, _ = first_touch_batch(path, side, k_stop * sigma, k_target * sigma)
    model.train(training)
    h, out = model(x, context)
    logits, time_return = model.outcome_head(h, torch.from_numpy(side.astype(np.float32)),
                                             torch.from_numpy(k_stop.astype(np.float32)),
                                             torch.from_numpy(k_target.astype(np.float32)))
    tensor = lambda a, scale: torch.from_numpy((a / scale).astype(np.float32))
    losses = {"return": pinball(out["returns"], tensor(y["return"], s["return_scale"]), QUANTILES),
              "excursion": pinball(out["up"], tensor(y["up"], s["excursion_scale"]), LEVEL_QUANTILES)
                           + pinball(out["down"], tensor(y["down"], s["excursion_scale"]), LEVEL_QUANTILES),
              "outcome": nn.functional.cross_entropy(logits, torch.from_numpy(category))}
    timed = torch.from_numpy(category == 2)
    error = (time_return - tensor(y["time_return"], s["return_scale"]))[timed]
    losses["time_return"] = (error ** 2).mean() if len(error) else torch.zeros(())
    return sum(LOSS_WEIGHTS[key] * value for key, value in losses.items()), {k: float(v) for k, v in losses.items()}


def predict(model, batches, rows, size=4096):
    """Representação e quantis em unidades de retorno log; nada de rótulo entra aqui."""
    model.eval()
    s = batches.scalers
    parts = {"h": [], "returns": [], "up": [], "down": [], "sigma": []}
    with torch.no_grad():
        for start in range(0, len(rows), size):
            raw, _, sigma, derivatives = batches.raw(rows[start:start + size])
            h, out = model(*batches.tensors(raw, sigma, derivatives))
            parts["h"].append(h)
            parts["returns"].append(out["returns"].numpy() * s["return_scale"])
            parts["up"].append(out["up"].numpy() * s["excursion_scale"])
            parts["down"].append(out["down"].numpy() * s["excursion_scale"])
            parts["sigma"].append(sigma)
    return {key: torch.cat(value) if key == "h" else np.concatenate(value) for key, value in parts.items()}


def side_levels(prediction, side, tau_stop, tau_target):
    """Distâncias log de stop e alvo a partir dos quantis de excursão: alvo na direção favorável."""
    i, j = LEVEL_QUANTILES.index(tau_stop), LEVEL_QUANTILES.index(tau_target)
    adverse, favorable = (prediction["down"], prediction["up"]) if side == 1 else (prediction["up"], prediction["down"])
    return np.maximum(adverse[:, i], VOL_FLOOR), np.maximum(favorable[:, j], VOL_FLOOR)


def outcome(model, prediction, side, stop, target, scalers, temperature=1.):
    """Probabilidades [N,3] e retorno no tempo (log) para um lado e níveis dados."""
    sigma = prediction["sigma"]
    with torch.no_grad():
        logits, time_return = model.outcome_head(
            prediction["h"], torch.full((len(sigma),), float(side)),
            torch.from_numpy((stop / sigma).astype(np.float32)), torch.from_numpy((target / sigma).astype(np.float32)))
    return torch.softmax(logits / temperature, 1).numpy().astype(np.float64), time_return.numpy() * scalers["return_scale"]


def expected_value(probabilities, side, stop, target, time_return):
    """Mesma conta de Engine._expected_value."""
    net = lambda exit_log, minutes: net_fraction(side, 1., np.exp(exit_log), minutes, **COSTS)
    return (probabilities[:, 0] * net(side * target, HORIZON / 2) + probabilities[:, 1] * net(-side * stop, HORIZON / 2)
            + probabilities[:, 2] * net(time_return, HORIZON))


def fit_temperature(logits_probabilities, labels):
    """Temperatura que minimiza a log-verossimilhança, por busca em grade (robusta e determinística)."""
    log_p = np.log(np.clip(logits_probabilities, 1e-12, 1))
    best = (math.inf, 1.)
    for temperature in np.exp(np.linspace(np.log(.25), np.log(4), 121)):
        scaled = log_p / temperature
        scaled -= scaled.max(1, keepdims=True)
        nll = -np.mean(scaled[np.arange(len(labels)), labels] - np.log(np.exp(scaled).sum(1)))
        best = min(best, (nll, float(temperature)))
    return best[1]


def temper(probabilities, temperature):
    scaled = np.log(np.clip(probabilities, 1e-12, 1)) / temperature
    scaled = np.exp(scaled - scaled.max(1, keepdims=True))
    return scaled / scaled.sum(1, keepdims=True)


def reliability(probabilities, labels, bins=10):
    """ECE, Brier e tabela de confiabilidade (um contra todos, por classe)."""
    one_hot = np.eye(len(CLASSES))[labels]
    table, ece = [], 0.
    for c, name in enumerate(CLASSES):
        p = probabilities[:, c]
        edges = np.minimum((p * bins).astype(int), bins - 1)
        for b in range(bins):
            mask = edges == b
            if mask.any():
                gap = abs(p[mask].mean() - one_hot[mask, c].mean())
                ece += gap * mask.sum() / (len(p) * len(CLASSES))
                table.append({"class": name, "bin": [b / bins, (b + 1) / bins], "count": int(mask.sum()),
                              "predicted": float(p[mask].mean()), "observed": float(one_hot[mask, c].mean())})
    base = one_hot.mean(0)
    return {"ece": float(ece), "brier": float(np.mean(np.sum((probabilities - one_hot) ** 2, 1))),
            "brier_base_rate": float(np.mean(np.sum((base - one_hot) ** 2, 1))), "table": table}


def policy_decisions(model, prediction, scalers, tau_stop, tau_target, temperature, allow_short=True):
    """Lado de maior valor esperado e seus níveis, probabilidades e valor, por decisão."""
    best = None
    for side in ((1, -1) if allow_short else (1,)):
        stop, target = side_levels(prediction, side, tau_stop, tau_target)
        probabilities, time_return = outcome(model, prediction, side, stop, target, scalers, temperature)
        value = expected_value(probabilities, side, stop, target, time_return)
        current = {"side": np.full(len(value), side), "stop": stop, "target": target,
                   "probabilities": probabilities, "value": value}
        if best is None:
            best = current
        else:
            better = value > best["value"]
            best = {key: np.where(better[:, None] if v.ndim == 2 else better, current[key], v) for key, v in best.items()}
    return best


def simulate(batches, rows, decisions, margin):
    """Uma posição por vez, como no motor: entra na abertura seguinte se o valor esperado supera a margem.
    Aproximação: decisões só nos minutos amostrados e sem inversão antecipada pelo modelo."""
    _, path, _, _ = batches.raw(rows)
    category, exit_raw, minutes = first_touch_batch(path, decisions["side"], decisions["stop"], decisions["target"])
    nets = net_fraction(decisions["side"], path[:, 0, 0], exit_raw, minutes, **COSTS)
    entry_time = batches.views.t0 + 60 * (batches.index[rows] + 1)
    busy_until, chosen = -1, []
    threshold = math.inf if margin is None else margin  # sem margem: a política não opera
    for i in np.flatnonzero(decisions["value"] > threshold):
        if entry_time[i] >= busy_until:
            chosen.append(i)
            busy_until = entry_time[i] + 60 * math.ceil(minutes[i])
    chosen = np.array(chosen, dtype=int)
    result = {"trades": len(chosen), "margin": margin}
    if len(chosen):
        net = nets[chosen]
        result.update(mean_net=float(net.mean()), total_net=float(net.sum()), win_rate=float((net > 0).mean()),
                      exits={name: int((category[chosen] == c).sum()) for c, name in enumerate(CLASSES)},
                      long_fraction=float((decisions["side"][chosen] == 1).mean()))
    return result


def interval_report(prediction, y, delta):
    low, high = prediction["returns"][:, 0] - delta, prediction["returns"][:, -1] + delta
    return {"coverage_90": float(np.mean((y >= low) & (y <= high))), "mean_width": float(np.mean(high - low)),
            "median_abs_error": float(np.mean(abs(prediction["returns"][:, 2] - y))),
            "zero_forecast_abs_error": float(np.mean(abs(y)))}


def evaluate(model, batches, rows, scalers, calibration):
    """Relatório completo de um conjunto com tudo congelado."""
    prediction = predict(model, batches, rows)
    raw, path, _, _ = batches.raw(rows)
    y = targets(path, raw["m1"][:, -1, 3])
    decisions = policy_decisions(model, prediction, scalers, calibration["tau_stop"], calibration["tau_target"],
                                 calibration["temperature"])
    labels, _, _ = first_touch_batch(path, decisions["side"], decisions["stop"], decisions["target"])
    return {"examples": len(rows), "interval": interval_report(prediction, y["return"], calibration["conformal_delta"]),
            "outcome_calibration": reliability(decisions["probabilities"], labels),
            "policy": simulate(batches, rows, decisions, calibration["ev_margin"])}


def calibrate(model, batches, rows, scalers):
    """Temperatura, conformal e política escolhidos só na metade de calibração."""
    prediction = predict(model, batches, rows)
    raw, path, _, _ = batches.raw(rows)
    y = targets(path, raw["m1"][:, -1, 3])["return"]
    scores = np.maximum(prediction["returns"][:, 0] - y, y - prediction["returns"][:, -1])
    level = min(1., math.ceil((len(y) + 1) * COVERAGE) / len(y))
    delta = float(np.quantile(scores, level, method="higher"))
    candidates = []
    for tau_stop in LEVEL_QUANTILES:
        for tau_target in LEVEL_QUANTILES:
            raw_decisions = policy_decisions(model, prediction, scalers, tau_stop, tau_target, 1.)
            labels, _, _ = first_touch_batch(path, raw_decisions["side"], raw_decisions["stop"], raw_decisions["target"])
            temperature = fit_temperature(raw_decisions["probabilities"], labels)
            decisions = policy_decisions(model, prediction, scalers, tau_stop, tau_target, temperature)
            for margin in MARGINS:
                result = simulate(batches, rows, decisions, margin)
                candidates.append({"tau_stop": tau_stop, "tau_target": tau_target, "temperature": temperature,
                                   "ev_margin": margin, **result})
    eligible = [c for c in candidates if c["trades"] >= MIN_TRADES and c["mean_net"] > 0]
    chosen = max(eligible, key=lambda c: c["mean_net"]) if eligible else None
    if chosen is None:
        # Nenhuma política lucrativa com amostra mínima: níveis medianos e margem infinita (não opera).
        fallback = next(c for c in candidates if c["tau_stop"] == .5 and c["tau_target"] == .5)
        chosen = {**fallback, "ev_margin": None}
    return {"temperature": chosen["temperature"], "conformal_delta": delta, "coverage_target": COVERAGE,
            "tau_stop": chosen["tau_stop"], "tau_target": chosen["tau_target"],
            "ev_margin": chosen["ev_margin"], "trades_on_calibration": chosen["trades"],
            "candidates": candidates}


def load(data):
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    for product in manifest["products"]:
        if sha256(data / product["path"]) != product["sha256"]:
            raise ValueError(f"Dataset alterado: {product['path']}")
    minutes = np.load(data / "minutes.npz")
    views = Views(minutes["times"], minutes["ohlcv"])
    splits = {name: dict(np.load(data / f"{name}.npz")) for name in ("train", "validation", "test")}
    return manifest, views, splits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(__file__).parent / "data" / "supervised_v2")
    parser.add_argument("--out", type=Path, default=ROOT / "Modelos" / "numerico_v2")
    parser.add_argument("--results", type=Path, default=Path(__file__).parent / "results" / "numerico_v2")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--patience", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--samples-per-epoch", type=int, default=300_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if min(args.epochs, args.patience, args.batch_size, args.samples_per_epoch) < 1:
        parser.error("Parâmetros devem ser positivos")
    for folder in (args.out, args.results):
        if folder.exists() and any(folder.iterdir()):
            parser.error(f"Pasta não vazia: {folder}; use uma nova pasta")
        folder.mkdir(parents=True, exist_ok=True)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    manifest, views, splits = load(args.data)
    if manifest["horizon_minutes"] != HORIZON:
        raise ValueError("Horizonte do dataset diferente do modelo")
    generator = np.random.default_rng(args.seed)
    train = Batches(views, splits["train"])
    sample = np.sort(generator.choice(len(train.index), min(50_000, len(train.index)), replace=False))
    scalers = fit_scalers(train, sample)
    train.scalers = scalers
    validation = Batches(views, splits["validation"], scalers)
    half = len(validation.index) // 2
    calibration_rows, evaluation_rows = np.arange(half), np.arange(half, len(validation.index))
    model = MultiHeadNet(len(scalers["context_mean"]))
    optimizer = torch.optim.AdamW(model.parameters(), lr=.001, weight_decay=.0001)
    checkpoint = args.out / "model.pt"
    history, best, waiting, best_epoch = [], math.inf, 0, None
    for epoch in range(1, args.epochs + 1):
        started = time.monotonic()
        rows = generator.choice(len(train.index), min(args.samples_per_epoch, len(train.index)), replace=False)
        totals = {}
        for start in range(0, len(rows), args.batch_size):
            optimizer.zero_grad()
            loss, parts = batch_loss(model, train, rows[start:start + args.batch_size], generator, True)
            if not torch.isfinite(loss):
                raise RuntimeError("Perda não finita")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.)
            optimizer.step()
            for key, value in parts.items():
                totals[key] = totals.get(key, 0.) + value * len(rows[start:start + args.batch_size]) / len(rows)
        # Níveis de validação com semente fixa: a perda é comparável entre épocas.
        fixed = np.random.default_rng(1234)
        with torch.no_grad():
            parts = [batch_loss(model, validation, calibration_rows[s:s + 4096], fixed, False)
                     for s in range(0, len(calibration_rows), 4096)]
        weights = [min(4096, len(calibration_rows) - s) for s in range(0, len(calibration_rows), 4096)]
        val_loss = float(sum(float(p[0]) * w for p, w in zip(parts, weights)) / sum(weights))
        row = {"epoch": epoch, **{f"train_{k}": v for k, v in totals.items()},
               "validation_calibration_loss": val_loss, "seconds": time.monotonic() - started}
        history.append(row)
        print(json.dumps(row), flush=True)
        if val_loss < best:
            best, best_epoch, waiting = val_loss, epoch, 0
            torch.save(model.state_dict(), checkpoint)
        else:
            waiting += 1
            if waiting >= args.patience:
                break
    model.load_state_dict(torch.load(checkpoint, weights_only=True, map_location="cpu"))
    calibration = calibrate(model, validation, calibration_rows, scalers)
    (args.results / "calibration_candidates.json").write_text(json.dumps(calibration.pop("candidates"), indent=2), encoding="utf-8")
    np.savez(args.out / "scalers.npz", **{key: np.asarray(value) for key, value in scalers.items()})
    config = {"seed": args.seed, "epochs_limit": args.epochs, "patience": args.patience, "batch_size": args.batch_size,
              "samples_per_epoch": args.samples_per_epoch, "optimizer": "AdamW", "learning_rate": .001,
              "weight_decay": .0001, "loss_weights": LOSS_WEIGHTS, "quantiles": QUANTILES,
              "level_quantiles": LEVEL_QUANTILES, "level_range_sigmas": LEVEL_RANGE, "horizon_minutes": HORIZON,
              "scales": {key: list(value) for key, value in SCALES.items()}, "classes": CLASSES,
              "derivative_features": manifest["derivative_features"], "costs": COSTS,
              "dataset_manifest_sha256": sha256(args.data / "manifest.json"),
              "versions": {name: version(name) for name in ("torch", "numpy", "polars")}}
    (args.out / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out / "calibration.json").write_text(json.dumps(calibration, indent=2), encoding="utf-8")
    evaluation = evaluate(model, validation, evaluation_rows, scalers, calibration)
    # Teste: aberto só agora, com modelo, calibração e política congelados.
    test = Batches(views, splits["test"], scalers)
    test_report = evaluate(model, test, np.arange(len(test.index)), scalers, calibration)
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "config": config, "counts": manifest["counts"],
              "derivative_coverage": manifest["derivative_coverage"], "epochs_executed": len(history),
              "best_epoch": best_epoch, "parameters": sum(p.numel() for p in model.parameters()),
              "history": history, "calibration": calibration, "validation_evaluation_half": evaluation,
              "test_retrospective": test_report,
              "limitations": ["Histórico já explorado; teste retrospectivo não é comprovação prospectiva independente",
                              "Simulação decide só nos minutos amostrados e não inverte posição antes da saída",
                              "Stop e alvo no mesmo candle contam como stop; execução na abertura idealizada",
                              "Liquidações fora; derivativos só a partir de sua cobertura histórica",
                              "Custos fixos hipotéticos; sem impostos, impacto ou latência"],
              "artifacts": {name: sha256(args.out / name) for name in ("model.pt", "scalers.npz", "config.json", "calibration.json")}}
    (args.out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("best_epoch", "calibration", "validation_evaluation_half", "test_retrospective")},
                     indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
