"""Pesquisa local de candles. Sem corretora, ML ou promessa de retorno."""

import argparse
import csv
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from html import escape
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class Candle:
    timestamp: datetime  # abertura; candle completo disponível após interval_seconds
    open: float
    high: float
    low: float
    close: float
    volume: float


def validate(candles, interval_seconds=3600):
    if not candles:
        raise ValueError("CSV sem candles")
    if not isinstance(interval_seconds, int) or interval_seconds <= 0:
        raise ValueError("Intervalo deve ser inteiro positivo em segundos")
    now = datetime.now(timezone.utc)
    for index, c in enumerate(candles):
        values = (c.open, c.high, c.low, c.close, c.volume)
        if not all(math.isfinite(x) for x in values):
            raise ValueError(f"Candle {index}: valores não finitos")
        if min(values[:4]) <= 0 or c.volume < 0:
            raise ValueError(f"Candle {index}: preço/volume inválido")
        if not c.low <= min(c.open, c.close) <= max(c.open, c.close) <= c.high:
            raise ValueError(f"Candle {index}: OHLC inconsistente")
        if c.timestamp.tzinfo is None or c.timestamp.utcoffset() != timedelta(0):
            raise ValueError(f"Candle {index}: timestamp deve ser UTC explícito")
        if c.timestamp + timedelta(seconds=interval_seconds) > now:
            raise ValueError(f"Candle {index}: candle ainda não fechado")
        if index and (c.timestamp - candles[index - 1].timestamp).total_seconds() != interval_seconds:
            raise ValueError(f"Candle {index}: lacuna, duplicata ou ordem temporal inválida")


def load_csv(path, interval_seconds=3600):
    candles = []
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        fields = {"timestamp", "open", "high", "low", "close", "volume"}
        if not fields.issubset(reader.fieldnames or []):
            raise ValueError("Cabeçalho necessário: timestamp,open,high,low,close,volume")
        for line, row in enumerate(reader, 2):
            try:
                candles.append(Candle(datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")),
                                      *(float(row[key]) for key in ("open", "high", "low", "close", "volume"))))
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError(f"Linha {line}: formato inválido") from error
    validate(candles, interval_seconds)
    return candles


def targets(candles, fast=5, slow=20):
    """Posição desejada após cada fechamento; None durante aquecimento."""
    if not isinstance(fast, int) or not isinstance(slow, int) or not 1 <= fast < slow:
        raise ValueError("Janelas inteiras devem satisfazer 1 <= fast < slow")
    short, long = deque(), deque()
    short_sum = long_sum = 0.0
    result = []
    for c in candles:
        short.append(c.close)
        long.append(c.close)
        short_sum += c.close
        long_sum += c.close
        if len(short) > fast:
            short_sum -= short.popleft()
        if len(long) > slow:
            long_sum -= long.popleft()
        result.append(None if len(long) < slow else int(short_sum / fast > long_sum / slow))
    return result


def simulate(candles, desired, initial=10000.0, fee_bps=10.0, slippage_bps=5.0):
    """Executa alvo do candle anterior na abertura atual; liquida no fim para comparação."""
    if len(candles) != len(desired) or not candles:
        raise ValueError("Candles e alvos devem ter mesmo tamanho não nulo")
    if any(value not in (None, 0, 1) for value in desired):
        raise ValueError("Alvos devem ser None, 0 ou 1")
    if not math.isfinite(initial) or initial <= 0:
        raise ValueError("Capital inicial deve ser positivo e finito")
    if not all(math.isfinite(x) and 0 <= x < 10000 for x in (fee_bps, slippage_bps)):
        raise ValueError("Custos devem estar entre 0 e 10000 bps, exclusive o limite superior")
    fee, slip = fee_bps / 10000, slippage_bps / 10000
    cash, units = initial, 0.0
    rows, trades = [], []
    peak, max_dd = initial, 0.0
    for i, c in enumerate(candles):
        target = desired[i - 1] if i else None
        action = "AGUARDAR"
        if target == 1 and units == 0:
            price = c.open * (1 + slip)
            units = cash / (price * (1 + fee))
            commission = units * price * fee
            cash = 0.0
            action = "COMPRAR"
        elif target == 0 and units > 0:
            price = c.open * (1 - slip)
            commission = units * price * fee
            cash = units * price - commission
            units = 0.0
            action = "VENDER"
        if action != "AGUARDAR":
            trades.append({"timestamp": c.timestamp.isoformat(), "action": action,
                           "price": price, "fee": commission})
        equity = cash + units * c.close
        peak = max(peak, equity)
        max_dd = max(max_dd, 1 - equity / peak)
        rows.append({"timestamp": c.timestamp.isoformat(), "close": c.close,
                     "target_at_close": desired[i], "action_at_open": action,
                     "cash": cash, "units": units, "equity_marked": equity})
    # Liquidação terminal é convenção de avaliação, separada dos sinais.
    liquidated = cash + units * candles[-1].close * (1 - slip) * (1 - fee)
    liquidation_fee = units * candles[-1].close * (1 - slip) * fee
    max_dd = max(max_dd, 1 - liquidated / peak)
    held = units > 0
    last_target = desired[-1]
    signal = "AGUARDAR" if last_target is None or bool(last_target) == held else (
        "COMPRAR" if last_target else "VENDER")
    summary = {"initial": initial, "final_marked": rows[-1]["equity_marked"],
               "final_liquidated": liquidated, "net_return": liquidated / initial - 1,
               "max_drawdown": max_dd, "orders_at_open": len(trades),
               "terminal_liquidation": held, "terminal_fee": liquidation_fee,
               "last_signal_for_next_open": signal,
               "fees_total": sum(t["fee"] for t in trades) + liquidation_fee}
    return summary, rows, trades


def chart(path, rows, label):
    """Artefato vetorial offline; eixo horizontal igualmente espaçado por candle."""
    values = [r["close"] for r in rows]
    low, high = min(values), max(values)
    span = high - low or 1
    points = [(60 + 880 * i / max(1, len(rows) - 1), 270 - 210 * (v - low) / span)
              for i, v in enumerate(values)]
    polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    markers = []
    for i, row in enumerate(rows):
        if row["action_at_open"] != "AGUARDAR":
            x, y = points[i]
            color = "#087f5b" if row["action_at_open"] == "COMPRAR" else "#c92a2a"
            title = escape(f'{row["action_at_open"]} na abertura {row["timestamp"]}')
            markers.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="{color}"><title>{title}</title></circle>')
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="350" role="img" aria-labelledby="title desc">
<title id="title">{escape(label)}</title><desc id="desc">Fechamento por candle; marcadores identificam candles de execução, não o preço executado.</desc>
<rect width="1000" height="350" fill="white"/><g font-family="sans-serif" font-size="14" fill="#222">
<text x="60" y="25">{escape(label)}</text><text x="5" y="65">{high:.2f}</text><text x="5" y="275">{low:.2f}</text>
<text x="60" y="300">{escape(rows[0]["timestamp"])}</text><text x="670" y="300">{escape(rows[-1]["timestamp"])}</text>
<text x="60" y="330">Verde: compra; vermelho: saída. Pontos marcam o candle, não o preço de execução.</text></g>
<polyline fill="none" stroke="#2455a4" stroke-width="2" points="{polyline}"/>{''.join(markers)}</svg>'''
    Path(path).write_text(svg, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--provenance", required=True, help="Origem ou identificação de dados sintéticos")
    parser.add_argument("--fast", type=int, default=5)
    parser.add_argument("--slow", type=int, default=20)
    parser.add_argument("--interval-seconds", type=int, default=3600)
    parser.add_argument("--fee-bps", type=float, default=10)
    parser.add_argument("--slippage-bps", type=float, default=5)
    parser.add_argument("--initial", type=float, default=10000)
    parser.add_argument("--out", type=Path, default=Path("results"))
    args = parser.parse_args()
    try:
        candles = load_csv(args.csv, args.interval_seconds)
        if len(candles) <= args.slow:
            raise ValueError("São necessários mais candles que a janela lenta")
        desired = targets(candles, args.fast, args.slow)
        config = dict(initial=args.initial, fee_bps=args.fee_bps, slippage_bps=args.slippage_bps)
        summary, rows, trades = simulate(candles, desired, **config)
        # Referência entra na mesma primeira abertura elegível da estratégia.
        baseline_targets = [None if i < args.slow - 1 else 1 for i in range(len(candles))]
        baseline, _, _ = simulate(candles, baseline_targets, **config)
    except (ValueError, OSError, OverflowError) as error:
        parser.error(str(error))
    args.out.mkdir(parents=True, exist_ok=True)
    report = {"asset": args.asset, "provenance": args.provenance,
              "sha256": hashlib.sha256(args.csv.read_bytes()).hexdigest(),
              "created_utc": datetime.now(timezone.utc).isoformat(),
              "parameters": {**config, "fast": args.fast, "slow": args.slow,
                             "interval_seconds": args.interval_seconds},
              "strategy": summary, "buy_hold_same_eligible_open": baseline,
              "cash_net_return": 0.0, "trades": trades,
              "warning": "Simulação histórica; não demonstra lucro futuro. Custos hipotéticos. Sem impostos ou impacto."}
    (args.out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    with (args.out / "equity.csv").open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    chart(args.out / "chart.svg", rows, f"{args.asset} | {args.provenance}")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Relatórios: {args.out.resolve()}")


if __name__ == "__main__":
    main()
