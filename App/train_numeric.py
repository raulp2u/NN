"""Referência zero, Ridge e CNN 1D com seleção temporal e teste retrospectivo único."""

import argparse
import csv
from datetime import datetime, timezone
from importlib.metadata import version
import json
import math
from pathlib import Path
import random
import time

import numpy as np
import polars as pl
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from torch.utils.tensorboard import SummaryWriter

from bitcoin_data import sha256


class NumericCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.Sequential(nn.Conv1d(8, 16, 3, padding=1), nn.GELU(),
                                    nn.Conv1d(16, 32, 3, padding=1), nn.GELU(),
                                    nn.AdaptiveAvgPool1d(1), nn.Flatten(),
                                    nn.Linear(32, 16), nn.GELU(), nn.Linear(16, 1))

    def forward(self, x):
        return self.layers(x).squeeze(-1)


def normalize(train_x, *others):
    scaler = StandardScaler().fit(train_x.transpose(0, 2, 1).reshape(-1, 8))
    def transform(x):
        return scaler.transform(x.transpose(0, 2, 1).reshape(-1, 8)).reshape(-1, 30, 8).transpose(0, 2, 1).copy().astype(np.float32)
    return scaler, [transform(x) for x in (train_x, *others)]


def metrics(y, prediction):
    error = np.asarray(prediction) - y
    mse = float(np.mean(error**2))
    denominator = float(np.sum((y-y.mean())**2))
    nonzero = np.abs(prediction) > 1e-12
    return {"mse_log_return": mse, "rmse_log_return": math.sqrt(mse),
            "mae_log_return": float(np.mean(abs(error))),
            "r2": 1-float(np.sum(error**2))/denominator if denominator else None,
            "direction_accuracy_on_nonzero_predictions": float(np.mean(np.sign(prediction[nonzero]) == np.sign(y[nonzero]))) if nonzero.any() else None,
            "nonzero_prediction_fraction": float(nonzero.mean())}


def cost_hurdle(fee_bps=10., slippage_bps=5.):
    fee, slip = fee_bps/10000, slippage_bps/10000
    if not (0 <= fee < 1 and 0 <= slip < 1):
        raise ValueError("Custos inválidos")
    return float(np.log((1+fee)/(1-fee)) + np.log((1+slip)/(1-slip)))


def simulated_policy(frame, prediction, fee_bps=10., slippage_bps=5.):
    """Operações independentes de 30m; futuros usados somente após a decisão."""
    fee, slip = fee_bps/10000, slippage_bps/10000
    hurdle = cost_hurdle(fee_bps, slippage_bps)
    decisions = np.asarray(prediction) > hurdle
    entry, exit_price = frame["execution_open_future"].to_numpy(), frame["exit_close_future"].to_numpy()
    factors = np.ones(len(frame))
    factors[decisions] = exit_price[decisions]*(1-slip)*(1-fee)/(entry[decisions]*(1+slip)*(1+fee))
    equity = np.r_[1., np.cumprod(factors)]
    drawdown = 1-equity/np.maximum.accumulate(equity)
    benchmark = float(exit_price[-1]*(1-slip)*(1-fee)/(entry[0]*(1+slip)*(1+fee))-1)
    return {"net_return": float(equity[-1]-1), "max_drawdown_at_horizon_closes": float(drawdown.max()),
            "round_trips": int(decisions.sum()), "orders": int(2*decisions.sum()),
            "prediction_hurdle_log_return": float(hurdle), "fee_bps_per_side": fee_bps,
            "slippage_bps_per_side": slippage_bps, "cash_return": 0.,
            "buy_hold_terminal_return": benchmark}, equity


def trade_ledger(frame, prediction, name, fee_bps=10., slippage_bps=5.):
    fee, slip = fee_bps/10000, slippage_bps/10000
    rows = []
    for i in np.flatnonzero(np.asarray(prediction) > cost_hurdle(fee_bps, slippage_bps)):
        row = frame.row(int(i), named=True)
        entry, exit_price = row["execution_open_future"]*(1+slip), row["exit_close_future"]*(1-slip)
        rows.append({"model": name, "window_id": row["window_id"],
                     "decision_utc": datetime.fromtimestamp(row["available_at_epoch"], timezone.utc).isoformat(),
                     "exit_utc": datetime.fromtimestamp(row["target_end_epoch"], timezone.utc).isoformat(),
                     "prediction_log_return": float(prediction[i]), "entry_price_with_slippage": entry,
                     "exit_price_with_slippage": exit_price,
                     "net_return": exit_price*(1-fee)/(entry*(1+fee))-1})
    return rows


def write_ledger(path, rows):
    fields = ["model", "window_id", "decision_utc", "exit_utc", "prediction_log_return",
              "entry_price_with_slippage", "exit_price_with_slippage", "net_return"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def refresh_financials(data, output):
    """Corrige somente contabilidade/relatório de uma execução, sem ajustar modelos."""
    report_path = output / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if sha256(data / "manifest.json") != report["config"]["dataset_manifest_sha256"]:
        raise ValueError("Dataset diferente do usado no treinamento")
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    frame, _, _ = load_split(data, manifest, "test")
    predictions = pl.read_csv(output / "predictions_test_retrospective.csv")
    if not predictions["window_id"].equals(frame["window_id"]):
        raise ValueError("Previsões não correspondem ao dataset")
    policies, ledger = {}, []
    for name in ("zero", "ridge", "cnn"):
        prediction = predictions[f"prediction_{name}"].to_numpy()
        policies[name], _ = simulated_policy(frame, prediction)
        ledger.extend(trade_ledger(frame, prediction, name))
        old = report["financial_test_retrospective"][name]
        if old["round_trips"] != policies[name]["round_trips"] or not np.isclose(old["net_return"], policies[name]["net_return"], atol=1e-12):
            raise ValueError("Correção alterou as operações; requer investigação antes de substituir relatório")
    report["financial_test_retrospective"] = policies
    report["financial_evaluation_revision"] = "Barreira exata log((1+taxa)/(1-taxa)) + log((1+slippage)/(1-slippage)); mesmas previsões, operações e retornos, sem retreino."
    write_ledger(output / "trades_test_retrospective.csv", ledger)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(json.dumps({"financial_revision_verified": True, "trades": ledger}, indent=2), flush=True)


def load_split(data, manifest, split):
    path = data / f"{split}.parquet"
    expected = next(p["sha256"] for p in manifest["products"] if p["path"] == path.name)
    if sha256(path) != expected:
        raise ValueError(f"Dataset alterado: {split}")
    frame = pl.read_parquet(path)
    if frame.height != manifest["counts"][split] or frame["split"].unique().to_list() != [split]:
        raise ValueError("Contrato da divisão não confere")
    x = frame["features"].to_numpy().reshape(-1, 8, 30).copy()
    y = frame["target_log_return"].to_numpy()
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Dataset não finito")
    return frame, x, y


def predict_cnn(model, x, mean, scale):
    model.eval()
    result = []
    with torch.no_grad():
        for start in range(0, len(x), 2048):
            result.append(model(torch.from_numpy(x[start:start+2048])).numpy())
    return np.concatenate(result).astype(np.float64)*scale+mean


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(__file__).parent / "data" / "supervised_v1")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "results" / "numeric_v1")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--patience", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--refresh-financials", action="store_true", help="Auditar contabilidade de execução existente, sem retreino")
    args = parser.parse_args()
    if args.refresh_financials:
        refresh_financials(args.data, args.out)
        return
    if min(args.epochs, args.patience, args.batch_size) < 1:
        parser.error("Parâmetros devem ser positivos")
    if args.out.exists() and any(args.out.iterdir()):
        parser.error("Pasta de execução não vazia; use uma nova pasta")
    args.out.mkdir(parents=True, exist_ok=True)
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    manifest_path = args.data / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    train_frame, train_x, train_y = load_split(args.data, manifest, "train")
    val_frame, val_x, val_y = load_split(args.data, manifest, "validation")
    scaler, (train_x, val_x) = normalize(train_x, val_x)
    y_mean, y_scale = float(train_y.mean()), float(train_y.std()) or 1.
    np.savez(args.out / "scalers.npz", feature_mean=scaler.mean_, feature_scale=scaler.scale_,
             target_mean=y_mean, target_scale=y_scale)
    config = {"seed": 42, "epochs_limit": args.epochs, "patience": args.patience,
              "batch_size": args.batch_size, "optimizer": "AdamW", "learning_rate": .001,
              "weight_decay": .0001, "ridge_alpha": 10., "loss": "MSE_on_train_standardized_target",
              "device": "cpu", "threads": 4, "selection_metric": "validation_mse_log_return",
              "dataset_manifest_sha256": sha256(manifest_path), "channels": manifest["feature_channels"],
              "versions": {name: version(name) for name in ("torch", "numpy", "polars", "scikit-learn")}}
    (args.out / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    ridge = Ridge(alpha=10.)
    started = time.monotonic()
    ridge.fit(train_x.reshape(len(train_x), -1), train_y)
    np.savez(args.out / "ridge.npz", coef=ridge.coef_, intercept=ridge.intercept_)
    validation_predictions = {"zero": np.zeros(len(val_y)),
                              "ridge": ridge.predict(val_x.reshape(len(val_x), -1)).astype(np.float64)}
    print(f"Ridge ajustada em {time.monotonic()-started:.1f}s", flush=True)
    model = NumericCNN()
    optimizer = torch.optim.AdamW(model.parameters(), lr=.001, weight_decay=.0001)
    train_target = ((train_y-y_mean)/y_scale).astype(np.float32)
    loader = DataLoader(TensorDataset(torch.from_numpy(train_x), torch.from_numpy(train_target)),
                        batch_size=args.batch_size, shuffle=True, generator=torch.Generator().manual_seed(42))
    writer = SummaryWriter(str(args.out / "tensorboard"))
    history, best, waiting = [], float("inf"), 0
    checkpoint = args.out / "cnn.pt"
    for epoch in range(1, args.epochs+1):
        started = time.monotonic()
        model.train()
        loss_sum = 0.
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            loss = nn.functional.mse_loss(model(batch_x), batch_y)
            if not torch.isfinite(loss):
                raise RuntimeError("Perda não finita")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.)
            optimizer.step()
            loss_sum += float(loss.detach())*len(batch_y)
        prediction = predict_cnn(model, val_x, y_mean, y_scale)
        val_metrics = metrics(val_y, prediction)
        train_loss = loss_sum/len(train_y)
        row = {"epoch": epoch, "train_mse_standardized": train_loss,
               "validation_mse_log_return": val_metrics["mse_log_return"],
               "seconds": time.monotonic()-started}
        history.append(row)
        writer.add_scalar("loss/train_standardized", train_loss, epoch)
        writer.add_scalar("loss/validation_log_return", row["validation_mse_log_return"], epoch)
        writer.flush()
        if row["validation_mse_log_return"] < best:
            best = row["validation_mse_log_return"]
            best_epoch, waiting = epoch, 0
            torch.save(model.state_dict(), checkpoint)
        else:
            waiting += 1
        print(json.dumps(row), flush=True)
        if waiting >= args.patience:
            break
    writer.close()
    model.load_state_dict(torch.load(checkpoint, weights_only=True, map_location="cpu"))
    validation_predictions["cnn"] = predict_cnn(model, val_x, y_mean, y_scale)
    val_results = {key: metrics(val_y, value) for key, value in validation_predictions.items()}
    selected = min(val_results, key=lambda name: val_results[name]["mse_log_return"])
    # Teste é aberto apenas após checkpoint, modelo e política estarem fixados.
    test_frame, test_x, test_y = load_split(args.data, manifest, "test")
    test_x = scaler.transform(test_x.transpose(0, 2, 1).reshape(-1, 8)).reshape(-1, 30, 8).transpose(0, 2, 1).copy().astype(np.float32)
    test_predictions = {"zero": np.zeros(len(test_y)),
                        "ridge": ridge.predict(test_x.reshape(len(test_x), -1)).astype(np.float64),
                        "cnn": predict_cnn(model, test_x, y_mean, y_scale)}
    test_results = {key: metrics(test_y, value) for key, value in test_predictions.items()}
    policies, equities = {}, {}
    for key, value in test_predictions.items():
        policies[key], equities[key] = simulated_policy(test_frame, value)
    write_ledger(args.out / "trades_test_retrospective.csv",
                 [row for key, prediction in test_predictions.items() for row in trade_ledger(test_frame, prediction, key)])
    for name, frame, y, predictions in (("validation", val_frame, val_y, validation_predictions),
                                         ("test_retrospective", test_frame, test_y, test_predictions)):
        table = frame.select("window_id", "available_at_epoch", "target_end_epoch", "target_log_return")
        table = table.with_columns([pl.Series(f"prediction_{key}", value) for key, value in predictions.items()])
        table.write_csv(args.out / f"predictions_{name}.csv")
    with (args.out / "history.csv").open("w", newline="", encoding="utf-8") as stream:
        output = csv.DictWriter(stream, fieldnames=list(history[0]))
        output.writeheader()
        output.writerows(history)
    summary = {"created_utc": datetime.now(timezone.utc).isoformat(), "config": config,
               "counts": manifest["counts"], "epochs_executed": len(history), "best_cnn_epoch": best_epoch,
               "cnn_parameters": sum(p.numel() for p in model.parameters()),
               "selected_by_validation": selected, "validation": val_results, "test_retrospective": test_results,
               "financial_test_retrospective": policies,
               "limitations": ["Histórico já explorado; teste retrospectivo não é comprovação prospectiva independente",
                               "Somente preços; nenhum ramo de notícias treinado",
                               "Política de operações de 30m usa preenchimento idealizado na abertura seguinte",
                               "Drawdown amostrado no fim de cada horizonte; sem máxima perda intraperíodo",
                               "Sem impostos, spread dinâmico, impacto ou latência; custos hipotéticos fixos"],
               "artifacts": {name: sha256(args.out / name) for name in ("cnn.pt", "ridge.npz", "scalers.npz", "config.json")}}
    (args.out / "report.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), constrained_layout=True)
    axes[0].plot([r["epoch"] for r in history], [r["validation_mse_log_return"] for r in history], label="CNN: validação")
    axes[0].axhline(val_results["zero"]["mse_log_return"], color="gray", linestyle="--", label="Previsão zero")
    axes[0].set(xlabel="Época", ylabel="MSE do retorno logarítmico", title="Seleção pelo erro de validação")
    axes[0].legend()
    for key, value in equities.items():
        axes[1].plot(value, label=key)
    axes[1].set(xlabel="Horizontes de 30 minutos", ylabel="Patrimônio inicial = 1", title="Simulação retrospectiva após custos")
    axes[1].legend()
    fig.savefig(args.out / "training.png", dpi=160)
    fig.savefig(args.out / "training.pdf")
    plt.close(fig)
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
