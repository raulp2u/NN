"""Dataset v2: visões causais de 1 min, 5 min e 1 h, derivativos e caminho futuro de cada decisão.

Os rótulos (retorno, excursões e desfecho de stop/alvo) não são gravados: saem do caminho futuro
de 1 minuto no treino, com as mesmas regras de trading_engine.first_touch.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import polars as pl

from bitcoin_data import sha256
from derivatives_data import FEATURES as DERIVATIVE_FEATURES, DerivativeSeries
from supervised_data import features

# Escala: (minutos por candle, candles na janela). Candles maiores alinhados à grade do relógio.
SCALES = {"m1": (1, 30), "m5": (5, 48), "h1": (60, 48)}
HORIZON = 30
CLASSES = ("alvo", "stop", "tempo")


def run_lengths(valid):
    """Quantidade de posições válidas consecutivas terminando em cada índice."""
    index = np.arange(len(valid))
    last_invalid = np.maximum.accumulate(np.where(valid, -1, index))
    return index - last_invalid


def aggregate(grid, factor):
    """Candles de `factor` minutos; NaN se algum minuto falta."""
    blocks = grid[:len(grid) // factor * factor].reshape(-1, factor, 5)
    result = np.stack([blocks[:, 0, 0], blocks[:, :, 1].max(1), blocks[:, :, 2].min(1),
                       blocks[:, -1, 3], blocks[:, :, 4].sum(1)], axis=1)
    result[np.isnan(blocks).any(axis=(1, 2))] = np.nan
    return result


class Views:
    """Grade de minutos com lacunas em NaN e agregados do relógio; mesma classe no treino e ao vivo."""

    def __init__(self, times, ohlcv):
        times, ohlcv = np.asarray(times, dtype=np.int64), np.asarray(ohlcv, dtype=np.float64)
        if len(times) == 0 or np.any(times % 60) or np.any(np.diff(times) <= 0):
            raise ValueError("Aberturas devem estar na grade de minuto e em ordem crescente")
        self.t0 = int(times[0] - times[0] % 3600)
        size = (int(times[-1]) - self.t0) // 60 + 1
        m1 = np.full((-(-size // 60) * 60, 5), np.nan)
        m1[(times - self.t0) // 60] = ohlcv
        self.grids = {"m1": m1, **{key: aggregate(m1, factor) for key, (factor, _) in SCALES.items() if factor > 1}}
        self.runs = {key: run_lengths(~np.isnan(grid[:, 0])) for key, grid in self.grids.items()}

    def index(self, open_times):
        return (np.asarray(open_times, dtype=np.int64) - self.t0) // 60

    def _positions(self, index):
        # Decisão após o fechamento do minuto `index`: index + 1 minutos encerrados.
        return {key: (index + 1) // factor - 1 for key, (factor, _) in SCALES.items()}

    def eligible(self, index, horizon=0):
        index = np.asarray(index)
        ok = np.ones(len(index), dtype=bool)
        for key, position in self._positions(index).items():
            length = SCALES[key][1]
            inside = (position >= length - 1) & (position < len(self.runs[key]))
            ok &= inside & (self.runs[key][np.clip(position, 0, len(self.runs[key]) - 1)] >= length)
        if horizon:
            end = index + horizon
            inside = end < len(self.runs["m1"])
            ok &= inside & (self.runs["m1"][np.clip(end, 0, len(self.runs["m1"]) - 1)] >= horizon + SCALES["m1"][1])
        return ok

    def inputs(self, index):
        """{escala: OHLCV [N,L,5]} das janelas encerradas até cada decisão."""
        result = {}
        for key, position in self._positions(np.asarray(index)).items():
            length = SCALES[key][1]
            result[key] = self.grids[key][position[:, None] - np.arange(length - 1, -1, -1)]
        return result

    def future(self, index, horizon=HORIZON):
        """OHLC [N,H,4] dos candles t+1 … t+H; nunca usado como entrada."""
        return self.grids["m1"][np.asarray(index)[:, None] + np.arange(1, horizon + 1), :4]


def model_inputs(raw):
    """Canais por escala, como em supervised_data.features."""
    return {key: features(value) for key, value in raw.items()}


def recent_volatility(raw_m1, horizon=HORIZON):
    """Desvio dos retornos log de 1 min da janela, escalado ao horizonte (trading_engine.volatility)."""
    returns = np.diff(np.log(raw_m1[:, :, 3]), axis=1)
    return returns.std(axis=1, ddof=1) * np.sqrt(horizon)


def first_touch_batch(path, side, stop_distance, target_distance):
    """Versão vetorizada de trading_engine.first_touch. path [N,H,4]; níveis em distância log > 0.
    Retorna (classe em CLASSES [N], preço bruto de saída [N], minutos na posição [N])."""
    side = np.asarray(side, dtype=np.float64)
    entry = path[:, 0, 0]
    stop, target = entry * np.exp(-side * stop_distance), entry * np.exp(side * target_distance)
    n, horizon = path.shape[:2]
    category = np.full(n, 2)
    exit_raw = path[:, -1, 3].copy()
    minutes = np.full(n, float(horizon))
    done = np.zeros(n, dtype=bool)

    def settle(mask, label, price, moment):
        nonlocal done
        mask = mask & ~done
        category[mask], exit_raw[mask], minutes[mask] = label, price[mask], moment
        done |= mask

    for j in range(horizon):
        o, high, low = path[:, j, 0], path[:, j, 1], path[:, j, 2]
        if j:
            settle((o - stop) * side <= 0, 1, o, j)
            settle((o - target) * side >= 0, 0, o, j)
        favorable, adverse = np.where(side == 1, high, low), np.where(side == 1, low, high)
        settle((adverse - stop) * side <= 0, 1, stop, j + .5)
        settle((favorable - target) * side >= 0, 0, target, j + .5)
    return category, exit_raw, minutes


def targets(path, close_now):
    """Retorno log até o fechamento do horizonte e excursões a partir da abertura de execução."""
    entry = path[:, 0, 0]
    return {"return": np.log(path[:, -1, 3] / close_now),
            "time_return": np.log(path[:, -1, 3] / entry),
            "up": np.log(path[:, :, 1].max(1) / entry),
            "down": -np.log(path[:, :, 2].min(1) / entry)}


def load_minutes(path):
    frame = pl.read_csv(path, schema_overrides={"timestamp": pl.String})
    times = frame["timestamp"].str.to_datetime(time_zone="UTC").dt.epoch("s").to_numpy()
    return times, frame.select("open", "high", "low", "close", "volume").to_numpy().astype(np.float64)


def assign_splits(available, end, boundaries):
    """Exemplo pertence à divisão que contém a decisão e o fim do rótulo; os demais são descartados."""
    split = np.full(len(available), "", dtype=object)
    for name, limits in boundaries.items():
        first = int(datetime.fromisoformat(limits["first_start_utc"].replace("Z", "+00:00")).timestamp())
        last = int(datetime.fromisoformat(limits["last_available_at_utc"].replace("Z", "+00:00")).timestamp())
        split[(available > first) & (end <= last)] = name
    return split


def build(data, derivatives, output, stride=5, horizon=HORIZON):
    if (output / "manifest.json").exists():
        raise ValueError("Dataset concluído já existe; use outra pasta para nova versão")
    source = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    products = {p["path"]: p for p in source["quality"]["products"]}
    digest = sha256(data / "btc_usdt_1m.csv")
    if digest != products["btc_usdt_1m.csv"]["sha256"]:
        raise ValueError("Fonte alterada: btc_usdt_1m.csv")
    times, ohlcv = load_minutes(data / "btc_usdt_1m.csv")
    views = Views(times, ohlcv)
    candidates = views.index(times[times % (stride * 60) == 0])
    candidates = candidates[views.eligible(candidates, horizon)]
    available = views.t0 + 60 * (candidates + 1)
    split = assign_splits(available, available + 60 * horizon, source["quality"]["split_boundaries"])
    keep = split != ""
    candidates, available, split = candidates[keep], available[keep], split[keep]
    series = DerivativeSeries.from_folder(derivatives)
    context = np.array([series.features(int(moment)) for moment in available], dtype=np.float32)
    output.mkdir(parents=True, exist_ok=True)
    np.savez(output / "minutes.npz", times=times, ohlcv=ohlcv)
    files, counts, coverage = [], {}, {}
    for name in ("train", "validation", "test"):
        mask = split == name
        if not mask.any():
            raise ValueError(f"Divisão vazia: {name}")
        np.savez(output / f"{name}.npz", index=candidates[mask], available=available[mask], derivatives=context[mask])
        counts[name] = int(mask.sum())
        coverage[name] = {"funding": float(context[mask, -2].mean()), "metrics": float(context[mask, -1].mean())}
    for name in ("minutes.npz", "train.npz", "validation.npz", "test.npz"):
        files.append({"path": name, "sha256": sha256(output / name), "bytes": (output / name).stat().st_size})
    derivative_manifest = Path(derivatives) / "manifest.json"
    summary = {"schema_version": 2, "created_utc": datetime.now(timezone.utc).isoformat(),
               "source_sha256": {"btc_usdt_1m.csv": digest,
                                 "derivatives_manifest.json": sha256(derivative_manifest) if derivative_manifest.exists() else None},
               "stride_minutes": stride, "horizon_minutes": horizon,
               "scales": {key: {"minutes_per_bar": f, "bars": n} for key, (f, n) in SCALES.items()},
               "derivative_features": DERIVATIVE_FEATURES, "derivative_coverage": coverage, "counts": counts,
               "label_rule": "decisão e fim do rótulo na mesma divisão; janelas e futuro contínuos, sem preencher lacunas",
               "targets": {"return": "log(close[t+H]/close[t])", "time_return": "log(close[t+H]/open[t+1])",
                           "up": "log(max high[t+1..t+H]/open[t+1])", "down": "-log(min low[t+1..t+H]/open[t+1])",
                           "outcome": "trading_engine.first_touch com níveis sorteados no treino"},
               "original_boundaries": source["quality"]["split_boundaries"], "products": files,
               "evaluation_scope": "Desenvolvimento retrospectivo; histórico já explorado. Exige avaliação prospectiva independente."}
    temporary = output / "manifest.json.part"
    temporary.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(output / "manifest.json")
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).parent
    parser.add_argument("--data", type=Path, default=here / "data" / "bitcoin")
    parser.add_argument("--derivatives", type=Path, default=here / "data" / "derivatives")
    parser.add_argument("--out", type=Path, default=here / "data" / "supervised_v2")
    parser.add_argument("--stride", type=int, default=5, help="Minutos entre decisões amostradas")
    args = parser.parse_args()
    if args.stride < 1:
        parser.error("Stride deve ser positivo")
    build(args.data, args.derivatives, args.out, args.stride)
