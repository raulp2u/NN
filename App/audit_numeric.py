"""Audita divisões, alvos e reprodução das previsões do checkpoint congelado."""

import argparse
from datetime import datetime
import json
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.preprocessing import StandardScaler
import torch

from bitcoin_data import sha256
from train_numeric import NumericCNN, load_split, metrics, predict_cnn


def audit(data, results):
    report = json.loads((results / "report.json").read_text(encoding="utf-8"))
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    if sha256(data / "manifest.json") != report["config"]["dataset_manifest_sha256"]:
        raise ValueError("Manifesto mudou após treinamento")
    for name, digest in report["artifacts"].items():
        if sha256(results / name) != digest:
            raise ValueError(f"Artefato alterado: {name}")
    frames, count, previous_target_end = {}, 0, None
    for split in ("train", "validation", "test"):
        frame, _, y = load_split(data, manifest, split)
        available = frame["available_at_epoch"].to_numpy()
        input_start = frame["input_start_epoch"].to_numpy()
        target_end = frame["target_end_epoch"].to_numpy()
        limit = int(datetime.fromisoformat(manifest["original_boundaries"][split]["last_available_at_utc"]).timestamp())
        if np.any(available-input_start != 1800) or np.any(target_end-available != 1800) or np.any(target_end > limit):
            raise ValueError("Duração ou fronteira de rótulos inválida")
        if np.any(np.diff(input_start) < 1800):
            raise ValueError("Entradas sobrepostas")
        if previous_target_end is not None and previous_target_end > input_start[0]:
            raise ValueError("Alvo atravessa a fronteira entre conjuntos")
        previous_target_end = target_end[-1]
        recomputed = np.log(frame["exit_close_future"].to_numpy()/frame["observed_close"].to_numpy())
        np.testing.assert_allclose(y, recomputed, rtol=0, atol=1e-15)
        count += frame.height
        frames[split] = frame
    scaler_values = np.load(results / "scalers.npz")
    # Conferência independente dos parâmetros de normalização contra o treino.
    raw_train = frames["train"]["features"].to_numpy().reshape(-1, 8, 30).transpose(0, 2, 1).reshape(-1, 8)
    ref = StandardScaler().fit(raw_train)
    np.testing.assert_allclose(ref.mean_, scaler_values["feature_mean"], rtol=1e-10, atol=1e-10)
    np.testing.assert_allclose(ref.scale_, scaler_values["feature_scale"], rtol=1e-10, atol=1e-10)
    train_y = frames["train"]["target_log_return"].to_numpy()
    np.testing.assert_allclose(train_y.mean(), scaler_values["target_mean"], rtol=0, atol=1e-15)
    np.testing.assert_allclose(train_y.std(), scaler_values["target_scale"], rtol=0, atol=1e-15)
    x = frames["test"]["features"].to_numpy().reshape(-1, 8, 30).copy()
    x = ref.transform(x.transpose(0, 2, 1).reshape(-1, 8)).reshape(-1, 30, 8).transpose(0, 2, 1).copy().astype(np.float32)
    torch.set_num_threads(4)
    model = NumericCNN()
    model.load_state_dict(torch.load(results / "cnn.pt", weights_only=True, map_location="cpu"))
    prediction = predict_cnn(model, x, float(scaler_values["target_mean"]), float(scaler_values["target_scale"]))
    saved = pl.read_csv(results / "predictions_test_retrospective.csv")
    if not saved["window_id"].equals(frames["test"]["window_id"]):
        raise ValueError("Previsões fora de ordem")
    np.testing.assert_allclose(prediction, saved["prediction_cnn"].to_numpy(), rtol=0, atol=1e-10)
    score = metrics(frames["test"]["target_log_return"].to_numpy(), prediction)
    if not np.isclose(score["mse_log_return"], report["test_retrospective"]["cnn"]["mse_log_return"], rtol=1e-12):
        raise ValueError("Métricas não reproduzidas")
    ledger = pl.read_csv(results / "trades_test_retrospective.csv")
    for name, summary in report["financial_test_retrospective"].items():
        selected = ledger.filter(pl.col("model") == name)
        compounded = float(np.prod(1+selected["net_return"].to_numpy())-1)
        if selected.height != summary["round_trips"] or not np.isclose(compounded, summary["net_return"], atol=1e-12):
            raise ValueError("Trilha de operações não reproduz o patrimônio")
    result = {"status": "passed", "examples_checked": count, "split_counts": manifest["counts"],
              "train_only_scaler_verified": True, "future_targets_recomputed": True,
              "split_boundaries_verified": True, "cnn_test_predictions_reproduced": len(prediction),
              "checkpoint_hash_verified": True, "trade_accounting_verified": True,
              "scope": "Verificação de software e reprodução; sem inferência de rentabilidade futura"}
    (results / "audit.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(__file__).parent / "data" / "supervised_v1")
    parser.add_argument("--results", type=Path, default=Path(__file__).parent / "results" / "numeric_v1")
    args = parser.parse_args()
    audit(args.data, args.results)
