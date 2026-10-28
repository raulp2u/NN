"""Dataset causal: 30 minutos observados -> retorno dos próximos 30 minutos."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import polars as pl

from bitcoin_data import sha256

CHANNELS = ["log_open", "log_high", "log_low", "log_close", "log1p_volume",
            "close_difference", "close_acceleration", "log_body"]
PRICE_FIELDS = ("open", "high", "low", "close", "volume")


def features(raw):
    """raw: [N,L,5] (L=30 no v1). Retorna [N,8,L], sem ajuste estatístico global."""
    raw = np.asarray(raw, dtype=np.float64)
    if raw.ndim != 3 or raw.shape[2] != 5 or raw.shape[1] < 3:
        raise ValueError("Esperado OHLCV com formato [N,L,5] e L >= 3")
    if not np.isfinite(raw).all() or (raw[:, :, :4] <= 0).any() or (raw[:, :, 4] < 0).any():
        raise ValueError("OHLCV não finito ou fora do domínio")
    o, high, low, close = [raw[:, :, i] for i in range(4)]
    if ((low > np.minimum(o, close)) | (high < np.maximum(o, close)) | (low > high)).any():
        raise ValueError("OHLC inconsistente")
    price = 100 * np.log(raw[:, :, :4] / raw[:, :1, :1])
    difference = np.zeros_like(close)
    difference[:, 1:] = 100 * np.diff(np.log(close), axis=1)
    acceleration = np.zeros_like(close)
    acceleration[:, 2:] = np.diff(difference[:, 1:], axis=1)
    return np.concatenate([price.transpose(0, 2, 1), np.log1p(raw[:, :, 4])[:, None, :],
                           difference[:, None, :], acceleration[:, None, :],
                           (100 * np.log(close / o))[:, None, :]], axis=1).astype(np.float32)


def label_masks(starts, ends, splits, boundaries):
    """Razões mutuamente exclusivas. A próxima janela completa é todo o futuro exigido."""
    starts, ends = np.asarray(starts), np.asarray(ends)
    if len(starts) != len(ends) or len(starts) != len(splits) or len(starts) == 0:
        raise ValueError("Metadados vazios ou com tamanhos diferentes")
    if np.any(ends - starts != 1800) or np.any(np.diff(starts) <= 0):
        raise ValueError("Janelas devem estar ordenadas e ter 30 minutos")
    if any(split not in boundaries for split in splits):
        raise ValueError("Divisão desconhecida")
    reasons = np.full(len(starts), "accepted", dtype=object)
    reasons[-1] = "no_future"
    for i in range(len(starts)-1):
        if splits[i] not in boundaries:
            raise ValueError("Divisão desconhecida")
        if starts[i+1] != ends[i]:
            reasons[i] = "future_gap"
        elif splits[i+1] != splits[i] or ends[i+1] > boundaries[splits[i]]:
            reasons[i] = "split_boundary"
    return reasons == "accepted", reasons


def build(data, output):
    if (output / "manifest.json").exists():
        raise ValueError("Dataset concluído já existe; use outra pasta para nova versão")
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    products = {p["path"]: p for p in manifest["quality"]["products"]}
    inputs = {}
    for name in ("snapshots_30m.csv", "splits.csv"):
        digest = sha256(data / name)
        if digest != products[name]["sha256"]:
            raise ValueError(f"Fonte alterada: {name}")
        inputs[name] = digest
    frame = pl.read_csv(data / "snapshots_30m.csv")
    splits_frame = pl.read_csv(data / "splits.csv")
    if frame.height != manifest["quality"]["windows"] or splits_frame.height != frame.height:
        raise ValueError("Contagens das fontes divergentes")
    if not frame.select("window_id", "start_utc", "available_at_utc").equals(
            splits_frame.select("window_id", "start_utc", "available_at_utc")):
        raise ValueError("Índices temporais das fontes não correspondem")
    if not (frame["samples"] == 30).all():
        raise ValueError("Janela incompleta")
    start = frame["start_utc"].str.to_datetime(time_zone="UTC").dt.epoch("s").to_numpy()
    end = frame["available_at_utc"].str.to_datetime(time_zone="UTC").dt.epoch("s").to_numpy()
    splits = splits_frame["split"].to_numpy()
    boundaries = {key: int(datetime.fromisoformat(value["last_available_at_utc"]).timestamp())
                  for key, value in manifest["quality"]["split_boundaries"].items()}
    accepted, reasons = label_masks(start, end, splits, boundaries)
    selected = np.flatnonzero(accepted)
    # Os campos futuros ficam separados e nunca são passados a features().
    columns = [f"{field}_{minute:02}" for minute in range(30) for field in PRICE_FIELDS]
    raw = frame.select(columns).to_numpy().reshape(-1, 30, 5)
    x = features(raw[selected])
    current_close = raw[selected, -1, 3]
    future_close = raw[selected+1, -1, 3]
    target = np.log(future_close / current_close)
    output.mkdir(parents=True, exist_ok=True)
    result = pl.DataFrame({"window_id": frame["window_id"].to_numpy()[selected],
                           "split": splits[selected], "input_start_epoch": start[selected],
                           "available_at_epoch": end[selected], "target_end_epoch": end[selected+1],
                           "target_log_return": target,
                           "observed_close": current_close,
                           "execution_open_future": raw[selected+1, 0, 0],
                           "exit_close_future": future_close,
                           "features": x.reshape(len(x), -1)})
    files, counts = [], {}
    for split in ("train", "validation", "test"):
        subset = result.filter(pl.col("split") == split)
        if subset.height == 0:
            raise ValueError(f"Divisão vazia: {split}")
        path = output / f"{split}.parquet"
        temporary = path.with_suffix(".parquet.part")
        subset.write_parquet(temporary, compression="zstd")
        temporary.replace(path)
        counts[split] = subset.height
        files.append({"path": path.name, "sha256": sha256(path), "bytes": path.stat().st_size})
    discarded = np.flatnonzero(~accepted)
    pl.DataFrame({"window_id": frame["window_id"].to_numpy()[discarded],
                  "split": splits[discarded], "reason": reasons[discarded].tolist()}).write_csv(output / "exclusions.csv")
    reason_counts = {str(key): int(value) for key, value in zip(*np.unique(reasons, return_counts=True))}
    summary = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
               "input_hashes": inputs, "input_windows": frame.height, "accepted": len(selected),
               "counts": counts, "reasons": reason_counts, "shape_per_example": [8, 30],
               "feature_channels": CHANNELS, "feature_layout": "channel_first_flattened_8x30_float32",
               "price_feature_unit": "100*log(price/first_open_of_input)",
               "target": "log(close(t+30min)/close(t))", "target_unit": "decimal_log_return",
               "normalization": "Nenhum ajuste global; scaler será ajustado somente no treino",
               "future_metadata_never_features": ["target_log_return", "execution_open_future", "exit_close_future", "target_end_epoch"],
               "label_boundary_rule": "target_end <= split_end; próxima janela contígua e da mesma divisão",
               "original_boundaries": manifest["quality"]["split_boundaries"], "products": files,
               "evaluation_scope": "Desenvolvimento retrospectivo; histórico já explorado. Exige avaliação prospectiva independente."}
    temporary = output / "manifest.json.part"
    temporary.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(output / "manifest.json")
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(__file__).parent / "data" / "bitcoin")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "data" / "supervised_v1")
    args = parser.parse_args()
    build(args.data, args.out)
