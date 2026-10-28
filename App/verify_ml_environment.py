"""Verifica as ferramentas localmente, sem baixar modelos ou treinar em dados financeiros."""

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import platform
import tempfile


def verify(output):
    import numpy as np
    import polars as pl
    import torch
    from sklearn.metrics import mean_squared_error
    from sklearn.preprocessing import StandardScaler
    from torch.utils.tensorboard import SummaryWriter
    from transformers import BertConfig, BertModel

    output.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(42)
    torch.set_num_threads(2)
    x = torch.randn(64, 2)
    y = 2 * x[:, :1] - .5 * x[:, 1:]
    model = torch.nn.Linear(2, 1)
    initial_weights = model.weight.detach().clone()
    optimizer = torch.optim.AdamW(model.parameters(), lr=.05)
    loss_fn = torch.nn.MSELoss()
    initial_loss = float(loss_fn(model(x), y).detach())
    writer = SummaryWriter(str(output / "tensorboard"))
    for step in range(100):
        optimizer.zero_grad()
        loss = loss_fn(model(x), y)
        loss.backward()
        if not all(parameter.grad is not None and torch.isfinite(parameter.grad).all() for parameter in model.parameters()):
            raise RuntimeError("Gradientes ausentes ou não finitos")
        optimizer.step()
        writer.add_scalar("verificacao_sintetica/mse", float(loss.detach()), step)
    writer.flush()
    writer.close()
    final_loss = float(loss_fn(model(x), y).detach())
    if final_loss >= initial_loss or torch.equal(initial_weights, model.weight):
        raise RuntimeError("Otimizador não demonstrou atualização e redução do erro sintético")
    conv_shape = list(torch.nn.Conv1d(5, 8, kernel_size=3)(torch.randn(4, 5, 30)).shape)
    if conv_shape != [4, 8, 28]:
        raise RuntimeError("Saída inesperada de Conv1d")
    # Encoder pequeno aleatório apenas para verificar integração; zero downloads.
    encoder = BertModel(BertConfig(vocab_size=128, hidden_size=32, num_hidden_layers=1,
                                   num_attention_heads=2, intermediate_size=64))
    encoder.eval()
    with torch.no_grad():
        text_shape = list(encoder(input_ids=torch.ones((2, 8), dtype=torch.long)).last_hidden_state.shape)
    if text_shape != [2, 8, 32]:
        raise RuntimeError("Saída inesperada do encoder textual")
    scaled = StandardScaler().fit_transform(x.numpy())
    if not np.allclose(scaled.mean(axis=0), 0, atol=1e-6):
        raise RuntimeError("Normalização sintética não verificada")
    if mean_squared_error(y.numpy(), model(x).detach().numpy()) >= initial_loss:
        raise RuntimeError("Integração de métricas não verificada")
    with tempfile.TemporaryDirectory(dir=output) as folder:
        csv_path, parquet = Path(folder) / "example.csv", Path(folder) / "example.parquet"
        frame = pl.DataFrame({"sample": [0, 1, 2], "value": [1.5, 2.5, 3.5]})
        frame.write_csv(csv_path)
        pl.read_csv(csv_path).write_parquet(parquet)
        if not pl.read_parquet(parquet).equals(frame):
            raise RuntimeError("Conversão CSV/Parquet não preservou amostra")
    report = {"status": "passed", "created_utc": datetime.now(timezone.utc).isoformat(),
              "python": platform.python_version(), "platform": platform.platform(),
              "versions": {name: version(name) for name in ("torch", "numpy", "polars", "scikit-learn", "transformers", "tensorboard", "matplotlib")},
              "torch_build_cuda": torch.version.cuda, "cuda_available_in_this_build": torch.cuda.is_available(),
              "verified_device": "cpu", "synthetic_initial_mse": initial_loss,
              "synthetic_final_mse": final_loss, "conv1d_output_shape": conv_shape,
              "random_text_encoder_output_shape": text_shape,
              "csv_parquet_roundtrip": True, "tensorboard_written": True,
              "pretrained_models_downloaded": False, "financial_model_trained": False}
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "results" / "environment_check")
    verify(parser.parse_args().out)
