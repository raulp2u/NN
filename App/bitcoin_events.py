"""Diferenças finitas causais e maiores episódios de BTCUSDT em todo o histórico."""

import argparse
from array import array
import csv
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from bitcoin_data import sha256


def iso(seconds):
    return datetime.fromtimestamp(int(seconds), timezone.utc).isoformat().replace("+00:00", "Z")


def derivatives(times, prices, horizon):
    """Tempos de disponibilidade em segundos. h em minutos; não atravessa lacunas."""
    if not isinstance(horizon, (int, np.integer)) or horizon < 1:
        raise ValueError("Horizonte deve ser inteiro positivo")
    if len(times) != len(prices) or np.any(np.diff(times) <= 0):
        raise ValueError("Tempos devem ser estritamente crescentes e casar com preços")
    if np.any(~np.isfinite(prices)) or np.any(prices <= 0):
        raise ValueError("Preços devem ser positivos e finitos")
    size = len(prices)
    log = np.log(prices)
    gaps = np.r_[0, np.cumsum(np.diff(times) != 60)]
    velocity = np.full(size, np.nan)
    acceleration = np.full(size, np.nan)
    if size > horizon:
        valid = gaps[horizon:] == gaps[:-horizon]
        velocity[horizon:] = np.where(valid, 100 * (log[horizon:] - log[:-horizon]) / horizon, np.nan)
    if size > 2 * horizon:
        valid = gaps[2*horizon:] == gaps[:-2*horizon]
        acceleration[2*horizon:] = np.where(valid, 100 * (log[2*horizon:] - 2 * log[horizon:-horizon] + log[:-2*horizon]) / horizon**2, np.nan)
    return velocity, acceleration


def read_history(path):
    times, prices, volumes = array("q"), array("d"), array("d")
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            times.append(int(datetime.fromisoformat(row["timestamp"]).timestamp()) + 60)
            prices.append(float(row["close"]))
            volumes.append(float(row["volume"]))
    return np.frombuffer(times, dtype=np.int64), np.frombuffer(prices, dtype=np.float64), np.frombuffer(volumes, dtype=np.float64)


def daily_extremes(times, values, direction):
    day = times // 86400
    starts = np.r_[0, np.flatnonzero(np.diff(day)) + 1]
    ends = np.r_[starts[1:], len(times)]
    result = []
    for start, end in zip(starts, ends):
        part = values[start:end]
        if np.all(np.isnan(part)):
            continue
        offset = np.nanargmax(part) if direction == "positive" else np.nanargmin(part)
        index = int(start + offset)
        if values[index] * (1 if direction == "positive" else -1) > 0:
            result.append(index)
    return sorted(result, key=lambda index: abs(values[index]), reverse=True)


def independent_peaks(indices, times, count=10, separation_hours=24):
    selected = []
    for index in indices:
        if all(abs(int(times[index]) - int(times[other])) >= separation_hours * 3600 for other in selected):
            selected.append(index)
            if len(selected) == count:
                break
    return selected


def split_at(timestamp, boundaries):
    for split, limits in boundaries.items():
        if limits["first_start_utc"] < timestamp <= limits["last_available_at_utc"]:
            return split
    return "outside_complete_window_bounds"


def record(index, horizon, order, direction, value, rank, times, prices, boundaries):
    support = horizon * order
    timestamp = iso(times[index])
    return {"metric": "velocity" if order == 1 else "acceleration", "horizon_minutes": horizon,
            "direction": direction, "rank": rank, "index": index, "peak_available_at_utc": timestamp,
            "support_start_utc": iso(times[index-support]),
            "value": float(value), "unit": "log_percent_per_minute" if order == 1 else "log_percent_per_minute_squared",
            "return_horizon_pct": 100 * (float(prices[index]) / float(prices[index-horizon]) - 1),
            "price_at_peak_usdt": float(prices[index]), "price_horizon_ago_usdt": float(prices[index-horizon]),
            "price_change_usdt": float(prices[index] - prices[index-horizon]),
            "existing_split": split_at(timestamp, boundaries)}


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_events(output, selected, times, prices, volumes):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    nrows = (len(selected) + 1) // 2
    fig, axes = plt.subplots(nrows, 2, figsize=(14, 2.8*nrows), squeeze=False, constrained_layout=True)
    context = []
    for ax, event in zip(axes.flat, selected):
        index = event["index"]
        offsets = np.arange(max(0, index-90), min(len(times), index+91))
        # Quebras são preservadas visualmente, com NaN antes do ponto após a lacuna.
        x = (times[offsets] - times[index]) / 60
        y = 100 * (prices[offsets] / prices[index] - 1)
        line = y.copy()
        line[np.r_[False, np.diff(times[offsets]) != 60]] = np.nan
        ax.plot(x, line, color="#1d4ed8", linewidth=1)
        ax.axvline(0, color="#b91c1c", linewidth=.8)
        ax.axvspan(-30, 0, alpha=.08, color="#1d4ed8")
        ax.set_title(f"{event['event_id']} | {event['peak_available_at_utc']}\nr30m={event['return_30m_pct']:+.2f}% | {event['selection_reason']}", fontsize=9)
        ax.set(xlabel="Minutos relativos ao pico (tempo de fechamento UTC)", ylabel="Preço relativo ao pico (%)")
        ax.grid(alpha=.2)
        for i, minute, relative in zip(offsets, x, y):
            context.append({"event_id": event["event_id"], "available_at_utc": iso(times[i]),
                            "relative_minute": float(minute), "close_usdt": float(prices[i]),
                            "volume_btc": float(volumes[i]), "price_relative_to_peak_pct": float(relative)})
    for ax in list(axes.flat)[len(selected):]:
        ax.set_visible(False)
    fig.suptitle("Maiores episódios de BTCUSDT: diferenças finitas e contexto de ±90 minutos\nAnálise retrospectiva: o contexto futuro é somente diagnóstico, nunca atributo de treino", fontsize=12)
    fig.savefig(output / "eventos.png", dpi=150)
    fig.savefig(output / "eventos.pdf")
    plt.close(fig)
    write_csv(output / "event_context.csv", context)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(__file__).parent / "data" / "bitcoin")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "results" / "bitcoin_events")
    args = parser.parse_args()
    manifest = json.loads((args.data / "manifest.json").read_text(encoding="utf-8"))
    history = args.data / "btc_usdt_1m.csv"
    expected = next(p["sha256"] for p in manifest["quality"]["products"] if p["path"] == history.name)
    actual = sha256(history)
    if actual != expected:
        raise ValueError("Histórico diverge do manifesto")
    times, prices, volumes = read_history(history)
    if len(times) != manifest["quality"]["candles"]:
        raise ValueError("Contagem diverge do manifesto")
    print(f"Carregados {len(times):,} candles", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    rankings, groups, statistics = [], {}, []
    v30 = None
    for horizon in (1, 5, 30):
        velocity, acceleration = derivatives(times, prices, horizon)
        if horizon == 30:
            v30 = velocity.copy()
        for order, values in ((1, velocity), (2, acceleration)):
            finite = values[np.isfinite(values)]
            statistics.append({"order": order, "horizon_minutes": horizon, "valid_points": len(finite),
                               "abs_p50": float(np.quantile(abs(finite), .5)),
                               "abs_p99": float(np.quantile(abs(finite), .99)),
                               "abs_p999": float(np.quantile(abs(finite), .999))})
            for direction in ("positive", "negative"):
                peaks = independent_peaks(daily_extremes(times, values, direction), times)
                rows = [record(i, horizon, order, direction, values[i], rank, times, prices,
                               manifest["quality"]["split_boundaries"]) for rank, i in enumerate(peaks, 1)]
                rankings.extend(rows)
                groups[(horizon, order, direction)] = rows
        print(f"Derivadas de {horizon} minuto(s) concluídas", flush=True)
    write_csv(args.out / "derivative_rankings.csv", rankings)
    # Núcleo de dez episódios pelo retorno de 30m; separar episódios por 48h.
    candidates = groups[(30, 1, "positive")] + groups[(30, 1, "negative")]
    candidates.sort(key=lambda row: abs(row["value"]), reverse=True)
    selected = []
    def add(row, reason):
        if all(abs(times[row["index"]] - times[other["index"]]) >= 48*3600 for other in selected):
            new = dict(row)
            new["selection_reason"] = reason
            selected.append(new)
    for row in candidates:
        if len(selected) >= 10:
            break
        add(row, "extremo_30m")
    for order in (1, 2):
        for direction in ("positive", "negative"):
            add(groups[(1, order, direction)][0], f"extremo_ordem_{order}_1m_{direction}")
    for number, event in enumerate(selected, 1):
        event["event_id"] = f"E{number:02}"
        index = event["index"]
        event["return_30m_pct"] = None if np.isnan(v30[index]) else float(100*np.expm1(v30[index]*30/100))
        # Como as derivadas, o retorno de 1m não atravessa lacunas.
        event["return_1m_pct"] = (float(100*(prices[index]/prices[index-1]-1))
                                  if times[index] - times[index-1] == 60 else None)
    write_csv(args.out / "research_events.csv", selected)
    (args.out / "analysis_manifest.json").write_text(json.dumps({
        "created_utc": datetime.now(timezone.utc).isoformat(), "source_sha256": actual,
        "candles": len(times), "statistics": statistics, "research_events": len(selected),
        "rankings_rows": len(rankings), "horizons_minutes": [1, 5, 30],
        "first_derivative": "100*(ln(P_t)-ln(P_t-h))/h",
        "second_derivative": "100*(ln(P_t)-2*ln(P_t-h)+ln(P_t-2h))/h^2",
        "timestamps": "Fechamento/disponibilidade idealizada, abertura do candle +60 segundos",
        "peak_filter": "Um extremo por dia UTC, depois distância mínima de 24h por ranking; 48h na seleção de pesquisa",
        "scope": "Todo o histórico, incluindo teste existente: exploração retrospectiva, sem inferência causal",
        "news": "Associações documentais separadas; não estima causalidade ou correlação estatística com notícias",
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    plot_events(args.out, selected, times, prices, volumes)
    print(json.dumps([{k: row[k] for k in ("event_id", "peak_available_at_utc", "return_30m_pct", "return_1m_pct", "selection_reason")}
                      for row in selected], indent=2), flush=True)


if __name__ == "__main__":
    main()
