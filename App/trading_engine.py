"""Motor único de decisão e corretora simulada, comum ao replay e ao paper trading.

Recebe somente candles fechados de um minuto, em ordem. A decisão tomada no fechamento
de t executa na abertura de t+1. Nenhum evento emitido depende de candles posteriores
ao instante em que é emitido; revisões retrospectivas são eventos separados e tardios.
"""

from collections import deque
from dataclasses import dataclass, field
import math
import random

MINUTE = 60
SIDES = {1: "comprada", -1: "vendida"}


@dataclass(frozen=True)
class Bar:
    open_time: int  # epoch em segundos da abertura; disponível em open_time + 60
    open: float
    high: float
    low: float
    close: float
    volume: float

    def validate(self):
        values = (self.open, self.high, self.low, self.close, self.volume)
        if not all(math.isfinite(x) for x in values) or min(values[:4]) <= 0 or self.volume < 0:
            raise ValueError(f"Candle inválido em {self.open_time}")
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError(f"OHLC inconsistente em {self.open_time}")
        if self.open_time % MINUTE:
            raise ValueError(f"Abertura fora da grade de minuto: {self.open_time}")


@dataclass(frozen=True)
class Signal:
    """Visão do modelo após um fechamento.

    direction: 1 alta, -1 queda, 0 sem vantagem. None: o motor decide comparando
    predicted_log_return com o custo de ida e volta de cada lado."""
    direction: int | None
    reason: str
    predicted_log_return: float | None = None
    horizon_minutes: int | None = None
    attributions: list | None = None
    stop_distance: float | None = None    # distância log prevista até o stop
    target_distance: float | None = None  # distância log prevista até o alvo
    details: dict = field(default_factory=dict)
    # Faixa do retorno log no horizonte: {"low", "high", "coverage"}; só informativa.
    interval: dict | None = None
    # Por lado (1, -1): {"p_target", "p_stop", "p_time", "stop_distance", "target_distance",
    # "time_return"}. Presente, o motor decide pelo valor esperado após custos.
    sides: dict | None = None
    ev_margin: float | None = 0.0  # None: a calibração não achou política lucrativa; não opera


@dataclass(frozen=True)
class Settings:
    stake: float = 50.0               # valor de cada operação na moeda de exibição
    fee_bps: float = 10.0             # por lado
    slippage_bps: float = 5.0         # por lado, sempre desfavorável
    allow_short: bool = True
    borrow_bps_per_hour: float = 0.1  # hipótese de custo da venda descoberta
    horizon_minutes: int | None = 30  # encerra por tempo; None desliga
    levels: bool = True               # stop e alvo; False desliga todos
    stop_k: float | None = 2.0        # stop provisório em desvios da volatilidade, sem previsão do modelo
    target_k: float | None = 2.0
    volatility_window: int = 30

    def validate(self):
        if not math.isfinite(self.stake) or self.stake <= 0:
            raise ValueError("Valor por operação deve ser positivo")
        for value in (self.fee_bps, self.slippage_bps, self.borrow_bps_per_hour):
            if not math.isfinite(value) or not 0 <= value < 10000:
                raise ValueError("Custos devem estar entre 0 e 10000 bps")
        if self.horizon_minutes is not None and self.horizon_minutes < 1:
            raise ValueError("Horizonte deve ser positivo")
        for k in (self.stop_k, self.target_k):
            if k is not None and (not math.isfinite(k) or k <= 0):
                raise ValueError("Múltiplos de stop e alvo devem ser positivos")

    def hurdle(self, side=1, minutes=30):
        """Retorno logarítmico mínimo para cobrir ida e volta, como em train_numeric.cost_hurdle."""
        fee, slip = self.fee_bps / 10000, self.slippage_bps / 10000
        cost = math.log((1 + fee) / (1 - fee)) + math.log((1 + slip) / (1 - slip))
        if side == -1:
            cost += self.borrow_bps_per_hour / 10000 * minutes / 60
        return cost


def net_fraction(side, entry_open, exit_raw, minutes, fee_bps, slippage_bps, borrow_bps_per_hour):
    """Resultado líquido por unidade de valor aplicado, com a aritmética de Engine._open/_close.
    Só operadores aritméticos: aceita números ou arrays NumPy (side em {1, -1})."""
    fee, slip = fee_bps / 10000, slippage_bps / 10000
    long = (side + 1) / 2
    units = long / (entry_open * (1 + slip) * (1 + fee)) + (1 - long) / (entry_open * (1 - slip))
    price_in, price_out = entry_open * (1 + side * slip), exit_raw * (1 - side * slip)
    gross = units * (exit_raw - entry_open) * side
    costs = units * slip * (exit_raw + entry_open) + units * fee * (price_out + price_in)
    return gross - costs - (1 - long) * borrow_bps_per_hour / 10000 * minutes / 60


def first_touch(path, side, stop_distance, target_distance):
    """Desfecho de uma entrada na abertura de path[0], com as regras de Engine._manage.

    path: [(open, high, low, close)] dos candles após a decisão, até o horizonte.
    Abertura além de um nível executa na abertura; stop e alvo no mesmo candle contam
    como stop. Retorna (motivo, preço bruto de saída, minutos na posição)."""
    entry = path[0][0]
    stop = entry * math.exp(-side * stop_distance) if stop_distance else None
    target = entry * math.exp(side * target_distance) if target_distance else None
    for j, (o, high, low, _) in enumerate(path):
        if j:
            if stop and (o - stop) * side <= 0:
                return "stop", o, j
            if target and (o - target) * side >= 0:
                return "alvo", o, j
        favorable, adverse = (high, low) if side == 1 else (low, high)
        if stop and (adverse - stop) * side <= 0:
            return "stop", stop, j + .5
        if target and (favorable - target) * side >= 0:
            return "alvo", target, j + .5
    return "tempo", path[-1][3], len(path)


def volatility(bars, horizon):
    """Desvio dos retornos log de 1m da janela, escalado ao horizonte. Somente passado."""
    closes = [bar.close for bar in bars]
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance * horizon)


def performance(trades, resamples=2000, seed=42, display=False):
    """Métricas de operações fechadas; intervalo bootstrap do resultado médio por operação."""
    unit = "display" if display else "quote"
    nets = [t[f"net_{unit}"] for t in trades]
    if not nets:
        return {"trades": 0}
    wins, losses = [x for x in nets if x > 0], [x for x in nets if x <= 0]
    balance, peak, drawdown = 0.0, 0.0, 0.0
    for x in nets:
        balance += x
        peak = max(peak, balance)
        drawdown = max(drawdown, peak - balance)
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(nets) for _ in nets) / len(nets) for _ in range(resamples))
    costs = sum((t["fees_quote"] + t["slippage_quote"] + t["borrow_quote"])
                * (t["rate_entry"] if display else 1.0) for t in trades)
    gross = sum(t["gross_quote"] * (t["rate_entry"] if display else 1.0) for t in trades)
    by = {}
    for key in ("side", "exit_reason"):
        for t in trades:
            group = by.setdefault(f"{key}:{t[key]}", {"trades": 0, f"net_{unit}": 0.0})
            group["trades"] += 1
            group[f"net_{unit}"] += t[f"net_{unit}"]
    return {"trades": len(nets), f"net_{unit}": sum(nets), f"gross_{unit}": gross, f"costs_{unit}": costs,
            "win_rate": len(wins) / len(nets),
            "average_win": sum(wins) / len(wins) if wins else None,
            "average_loss": sum(losses) / len(losses) if losses else None,
            "profit_factor": sum(wins) / -sum(losses) if losses and sum(losses) < 0 else None,
            f"max_drawdown_{unit}": drawdown, f"mean_net_{unit}": sum(nets) / len(nets),
            "mean_net_ci90": [means[int(.05 * resamples)], means[int(.95 * resamples) - 1]],
            "ambiguous_bars": sum(bool(t["ambiguous"]) for t in trades), "groups": by}


class Engine:
    def __init__(self, model, settings=None, fx=None):
        """model: objeto com window, level_triggered, reset() e update(bar) -> Signal | None.
        fx: função(open_time) -> cotação da moeda de exibição por unidade de cotação, ou None."""
        settings = settings or Settings()
        settings.validate()
        self.model, self.settings, self.fx = model, settings, fx
        self.recent = deque(maxlen=max(240, model.window, settings.volatility_window) + 1)
        self.position = None
        self.pending = None
        self.last_direction = None
        self.realized = 0.0
        self.realized_display = 0.0
        self.trades = []
        self.reviews = []
        self.outcomes = []
        self.baseline = None
        self.counter = 0
        self.trade_counter = 0
        self.previous = None
        self._last_decision = None
        self._fx_missing = False
        self.warming = False  # ao vivo: candles de aquecimento já passados não geram ordens
        self.recovering_position = False

    # Eventos são dicionários simples, prontos para JSON e para o log SQLite.
    def _event(self, kind, time, **payload):
        return {"kind": kind, "time": time, **payload}

    def on_bar(self, bar):
        bar.validate()
        events = [self._event("candle", bar.open_time, open=bar.open, high=bar.high,
                              low=bar.low, close=bar.close, volume=bar.volume)]
        if self.previous is not None and bar.open_time <= self.previous.open_time:
            raise ValueError("Candle duplicado ou fora de ordem")
        if self.warming:
            self.pending = None
            self.last_direction = None
            self.recovering_position |= self.position is not None
        elif self.recovering_position:
            self.pending = None
            self.recovering_position = False
            if self.position:
                events += self._close(bar, bar.open, "lacuna", "open")
        if self.previous is not None and bar.open_time - self.previous.open_time != MINUTE:
            missing = (bar.open_time - self.previous.open_time) // MINUTE - 1
            events.append(self._event("alert", bar.open_time, level="warning", code="gap",
                                      message=f"Lacuna de {missing} minuto(s); modelo reiniciado, sem decisão até completar a janela"))
            if self.pending is not None:
                events.append(self._event("alert", bar.open_time, level="warning", code="order_cancelled",
                                          message="Ordem pendente cancelada pela lacuna"))
            self.pending = None
            if self.position and not self.warming:
                events += self._close(bar, bar.open, "lacuna", "open")
            self.model.reset()
            self.recent.clear()
            self.last_direction = None
        elif self.pending is not None:
            events += self._execute(bar)
        if self.position and not self.warming:
            events += self._manage(bar)
        missing = self.fx is not None and self._rate(bar.open_time) is None
        if missing != self._fx_missing:
            events.append(self._event("alert", bar.open_time, level="warning" if missing else "info",
                                      code="fx_missing" if missing else "fx_restored",
                                      message="Cotação de câmbio indisponível; novas entradas suspensas" if missing
                                      else "Cotação de câmbio restabelecida"))
            self._fx_missing = missing
        self.recent.append(bar)
        events += self._resolve(bar)
        events.append(self._equity(bar))
        if self.warming and hasattr(self.model, "observe"):
            # Modelos com janela longa só guardam o candle no aquecimento, sem inferência.
            self.model.observe(bar)
            signal = None
        else:
            signal = self.model.update(bar)
        if signal is not None:
            events += self._decide(bar, signal)
        self.previous = bar
        return events

    def _rate(self, time):
        if self.fx is None:
            return 1.0
        rate = self.fx(time)
        if rate is None or not math.isfinite(rate) or rate <= 0:
            return None
        return rate

    def _decide(self, bar, signal):
        s = self.settings
        available = bar.open_time + MINUTE
        current = self.position["side"] if self.position else 0
        horizon = signal.horizon_minutes or s.horizon_minutes or 30
        desired, reason_text = signal.direction, signal.reason
        values, evaluated = None, None
        stop_distance, target_distance = signal.stop_distance, signal.target_distance
        if desired is None and signal.sides:
            values = {side: self._expected_value(side, v, horizon) for side, v in signal.sides.items()}
            allowed = [side for side in values if side == 1 or s.allow_short]
            evaluated = max(allowed or values, key=values.get)
            text = " / ".join(f"{'compra' if side == 1 else 'venda'} {100 * value:+.3f}%"
                              for side, value in sorted(values.items(), reverse=True))
            if signal.ev_margin is None:
                desired = 0
                reason_text += f"; valor esperado após custos {text}; política sem margem lucrativa na calibração, não opera"
            elif allowed and values[evaluated] > signal.ev_margin:
                desired = evaluated
                reason_text += f"; valor esperado após custos {text} supera a margem de {100 * signal.ev_margin:.3f}%"
            else:
                desired = 0
                reason_text += f"; valor esperado após custos {text} não supera a margem de {100 * signal.ev_margin:.3f}%"
            stop_distance = signal.sides[evaluated]["stop_distance"]
            target_distance = signal.sides[evaluated]["target_distance"]
        elif desired is None:
            predicted = signal.predicted_log_return
            long_cost, short_cost = s.hurdle(1), s.hurdle(-1, horizon)
            if predicted > long_cost:
                desired = 1
                reason_text += f"; previsão {100 * predicted:+.3f}% supera custo {100 * long_cost:.3f}%"
            elif predicted < -short_cost:
                desired = -1
                reason_text += f"; previsão {100 * predicted:+.3f}% supera custo da venda {100 * short_cost:.3f}%"
            else:
                desired = 0
                reason_text += f"; previsão {100 * predicted:+.3f}% não cobre o custo de {100 * long_cost:.3f}%"
        signal_direction = desired
        if desired == -1 and not s.allow_short:
            desired = 0
            reason_text += "; venda descoberta desligada"
        if self.model.level_triggered and desired == self.last_direction and current != desired:
            # Modelo de estado (médias móveis): após saída forçada, só reentra em nova mudança.
            action, target = "AGUARDAR", None
            reason = reason_text + "; aguardando nova mudança após saída forçada"
        elif desired == current:
            action, target, reason = ("MANTER" if current else "AGUARDAR"), None, reason_text
        elif desired == 0 and not self.model.level_triggered:
            # Modelo de oportunidade (CNN): sem vantagem não força saída; tempo, stop e alvo encerram.
            action, target, reason = ("MANTER" if current else "AGUARDAR"), None, reason_text
        else:
            target = desired
            action = {1: "COMPRAR", -1: "VENDER A DESCOBERTO", 0: "ZERAR"}[desired]
            if current and desired:
                action = f"INVERTER: {action}"
            reason = reason_text
        if self._rate(bar.open_time) is None and target not in (None, 0):
            action, target, reason = "AGUARDAR", None, reason + "; sem cotação de câmbio"
        if self.warming:
            action, target, reason = "AQUECIMENTO", None, reason + "; candle histórico de aquecimento, sem ordem"
        self.last_direction = None if self.warming else desired
        self.pending = target
        self.counter += 1
        decision_id = self.counter
        sigma = volatility(list(self.recent)[-s.volatility_window:], s.horizon_minutes or 30)
        record = self._event("decision", bar.open_time, id=decision_id, available_at=available,
                             action=action, reason=reason, direction=signal_direction,
                             predicted_log_return=signal.predicted_log_return,
                             horizon_minutes=signal.horizon_minutes, attributions=signal.attributions,
                             volatility=sigma, close=bar.close, details=signal.details,
                             stop_distance=stop_distance, target_distance=target_distance,
                             hurdle_long=s.hurdle(1), hurdle_short=s.hurdle(-1, horizon),
                             interval=signal.interval, sides=signal.sides, evaluated_side=evaluated,
                             expected_values=values, ev_margin=signal.ev_margin if values else None)
        self._last_decision = record
        events = [record]
        if not self.warming and signal.predicted_log_return is not None and signal.horizon_minutes:
            self.outcomes.append({"decision_id": decision_id, "time": bar.open_time, "close": bar.close,
                                  "due": available + signal.horizon_minutes * MINUTE,
                                  "predicted": signal.predicted_log_return, "interval": signal.interval,
                                  "side": evaluated, "probabilities": signal.sides[evaluated] if evaluated else None,
                                  "stop_distance": stop_distance, "target_distance": target_distance})
        return events

    def _expected_value(self, side, v, horizon):
        """Resultado líquido esperado por unidade aplicada, entrando na próxima abertura (referência 1)."""
        s = self.settings
        def net(exit_log, minutes):
            return net_fraction(side, 1.0, math.exp(exit_log), minutes, s.fee_bps, s.slippage_bps, s.borrow_bps_per_hour)
        return (v["p_target"] * net(side * v["target_distance"], horizon / 2)
                + v["p_stop"] * net(-side * v["stop_distance"], horizon / 2)
                + v["p_time"] * net(v["time_return"], horizon))

    def _execute(self, bar):
        events = []
        target, self.pending = self.pending, None
        decision = self._last_decision
        if self.position and self.position["side"] != target:
            events += self._close(bar, bar.open, "modelo", "open")
        if target and not self.position:
            events += self._open(bar, target, decision)
        return events

    def _open(self, bar, side, decision):
        s = self.settings
        fee, slip = s.fee_bps / 10000, s.slippage_bps / 10000
        rate = self._rate(bar.open_time)
        if rate is None:
            self.last_direction = None
            return [self._event("alert", bar.open_time, level="warning", code="order_cancelled",
                                message="Entrada cancelada: câmbio indisponível na execução")]
        stake_quote = s.stake / rate
        if side == 1:
            price = bar.open * (1 + slip)
            units = stake_quote / (price * (1 + fee))
        else:
            price = bar.open * (1 - slip)
            units = stake_quote / price
        decision = decision or {}
        sigma = decision.get("volatility") or 0.0
        stop_d, target_d = decision.get("stop_distance"), decision.get("target_distance")
        source = "modelo" if stop_d or target_d else "provisorio_volatilidade"
        if stop_d is None and s.stop_k and sigma > 0:
            stop_d = s.stop_k * sigma
        if target_d is None and s.target_k and sigma > 0:
            target_d = s.target_k * sigma
        stop = bar.open * math.exp(-side * stop_d) if s.levels and stop_d else None
        target = bar.open * math.exp(side * target_d) if s.levels and target_d else None
        self.trade_counter += 1
        self.position = {"id": self.trade_counter, "side": side, "entry_time": bar.open_time, "entry_raw": bar.open,
                         "entry_price": price, "units": units, "stake_quote": stake_quote, "rate_entry": rate,
                         "stop": stop, "target": target, "age": 0, "best": bar.open, "worst": bar.open,
                         "decision_id": decision.get("id"),
                         "predicted_log_return": decision.get("predicted_log_return"),
                         "levels_source": source if (stop or target) else "desligado"}
        return [self._event("order", bar.open_time, trade_id=self.trade_counter, action="abrir", side=SIDES[side],
                            price=price, raw_price=bar.open, units=units, stake_quote=stake_quote,
                            stake_display=s.stake, rate=rate, stop=stop, target=target,
                            levels_source=self.position["levels_source"],
                            decision_id=self.position["decision_id"])]

    def _manage(self, bar):
        p = self.position
        side = p["side"]
        fresh = p["entry_time"] == bar.open_time
        if not fresh:
            # Abertura além do nível: execução na abertura, não no nível.
            if p["stop"] and (bar.open - p["stop"]) * side <= 0:
                return self._close(bar, bar.open, "stop", "open")
            if p["target"] and (bar.open - p["target"]) * side >= 0:
                return self._close(bar, bar.open, "alvo", "open")
        favorable, adverse = (bar.high, bar.low) if side == 1 else (bar.low, bar.high)
        hit_stop = p["stop"] is not None and (adverse - p["stop"]) * side <= 0
        hit_target = p["target"] is not None and (favorable - p["target"]) * side >= 0
        if hit_stop:
            # Com os dois níveis no mesmo candle, a ordem é desconhecida: assume o stop.
            p["worst"] = p["stop"]
            return self._close(bar, p["stop"], "stop", "intrabar", ambiguous=hit_target)
        p["worst"] = adverse if (adverse - p["worst"]) * side < 0 else p["worst"]
        if hit_target:
            p["best"] = p["target"]
            return self._close(bar, p["target"], "alvo", "intrabar")
        p["best"] = favorable if (favorable - p["best"]) * side > 0 else p["best"]
        p["age"] += 1
        horizon = self.settings.horizon_minutes
        if horizon and p["age"] >= horizon:
            return self._close(bar, bar.close, "tempo", "close")
        return []

    def _close(self, bar, raw, reason, moment, ambiguous=False):
        s = self.settings
        p, self.position = self.position, None
        fee, slip = s.fee_bps / 10000, s.slippage_bps / 10000
        side, units = p["side"], p["units"]
        price = raw * (1 - slip) if side == 1 else raw * (1 + slip)
        exit_time = bar.open_time + (MINUTE if moment == "close" else 0)
        # Saída dentro do candle: horário exato desconhecido, conta meio minuto.
        minutes = (exit_time - p["entry_time"] + (30 if moment == "intrabar" else 0)) / 60
        gross = units * (raw - p["entry_raw"]) * side
        slippage = units * slip * (raw + p["entry_raw"])
        fees = units * fee * (price + p["entry_price"])
        borrow = p["stake_quote"] * s.borrow_bps_per_hour / 10000 * minutes / 60 if side == -1 else 0.0
        net = gross - slippage - fees - borrow
        rate_exit = self._rate(bar.open_time) or p["rate_entry"]
        net_display = (p["stake_quote"] + net) * rate_exit - s.stake
        fx_effect = net_display - net * p["rate_entry"]
        self.realized += net
        self.realized_display += net_display
        trade = {"id": p["id"], "side": SIDES[side], "entry_time": p["entry_time"], "entry_raw": p["entry_raw"],
                 "entry_price": p["entry_price"], "exit_time": exit_time, "exit_bar": bar.open_time,
                 "exit_moment": moment, "exit_raw": raw, "exit_price": price, "exit_reason": reason,
                 "ambiguous": ambiguous, "minutes": minutes, "units": units, "stake_quote": p["stake_quote"],
                 "stake_display": s.stake, "rate_entry": p["rate_entry"], "rate_exit": rate_exit,
                 "gross_quote": gross, "fees_quote": fees, "slippage_quote": slippage, "borrow_quote": borrow,
                 "net_quote": net, "net_pct": net / p["stake_quote"], "net_display": net_display,
                 "fx_effect_display": fx_effect, "stop": p["stop"], "target": p["target"],
                 "levels_source": p["levels_source"],
                 "best_pct": side * math.log(p["best"] / p["entry_raw"]),
                 "worst_pct": side * math.log(p["worst"] / p["entry_raw"]),
                 "decision_id": p["decision_id"], "predicted_log_return": p["predicted_log_return"],
                 "balance_display": self.realized_display}
        self.trades.append(trade)
        self.reviews.append({"trade": trade, "due": exit_time + 30 * MINUTE})
        return [self._event("order", bar.open_time, trade_id=p["id"], action="fechar", side=SIDES[side],
                            price=price, raw_price=raw, reason=reason, moment=moment),
                self._event("trade", bar.open_time, **trade)]

    def _resolve(self, bar):
        """Eventos tardios: desfecho das previsões e revisão retrospectiva das operações."""
        events, now = [], bar.open_time + MINUTE
        closes = {b.open_time + MINUTE: b.close for b in self.recent}
        pending = []
        for item in self.outcomes:
            if now < item["due"]:
                pending.append(item)
            elif item["due"] in closes:
                realized = math.log(closes[item["due"]] / item["close"])
                extra = {}
                if item.get("interval"):
                    extra["inside_interval"] = item["interval"]["low"] <= realized <= item["interval"]["high"]
                if item.get("side"):
                    # Desfecho real do lado avaliado, com os mesmos níveis e regras da operação.
                    path = [(b.open, b.high, b.low, b.close) for b in self.recent
                            if item["time"] < b.open_time < item["due"]]
                    if len(path) == (item["due"] - item["time"]) // MINUTE - 1:
                        category, _, _ = first_touch(path, item["side"], item["stop_distance"], item["target_distance"])
                        extra.update(side=item["side"], category=category,
                                     probabilities={key: item["probabilities"][key]
                                                    for key in ("p_target", "p_stop", "p_time")})
                events.append(self._event("outcome", bar.open_time, decision_id=item["decision_id"],
                                          decision_time=item["time"], predicted=item["predicted"],
                                          realized=realized, error=item["predicted"] - realized, **extra))
        self.outcomes = pending
        pending = []
        for item in self.reviews:
            if now < item["due"]:
                pending.append(item)
                continue
            t = item["trade"]
            side = 1 if t["side"] == "comprada" else -1
            what_if = {}
            for offset in (-15, -5, 5, 15, 30):
                moment = t["exit_time"] + offset * MINUTE
                if moment in closes and moment > t["entry_time"]:
                    what_if[str(offset)] = side * math.log(closes[moment] / t["entry_raw"])
            best = t["best_pct"]
            captured = side * math.log(t["exit_raw"] / t["entry_raw"])
            events.append(self._event("review", bar.open_time, trade_id=t["id"], retrospective=True,
                                      exit_efficiency=captured / best if best > 0 else None,
                                      captured_log_return=captured, what_if_log_return=what_if))
        self.reviews = pending
        return events

    def _equity(self, bar):
        s = self.settings
        fee, slip = s.fee_bps / 10000, s.slippage_bps / 10000
        rate = self._rate(bar.open_time)
        if self.baseline is None and rate is not None and not self.warming:
            stake_quote = s.stake / rate
            self.baseline = stake_quote / (bar.open * (1 + slip) * (1 + fee)), stake_quote
        open_net = open_gross = None
        if self.position:
            p = self.position
            exit_price = bar.close * (1 - slip) if p["side"] == 1 else bar.close * (1 + slip)
            open_gross = p["units"] * (bar.close - p["entry_raw"]) * p["side"]
            open_net = (open_gross - p["units"] * slip * (bar.close + p["entry_raw"])
                        - p["units"] * fee * (exit_price + p["entry_price"]))
        baseline = None
        if self.baseline:
            units, stake_quote = self.baseline
            baseline = (units * bar.close * (1 - slip) * (1 - fee) - stake_quote) * (rate or 1.0)
        to_display = rate or 1.0
        position = None
        if self.position:
            p = self.position
            position = {"id": p["id"], "side": SIDES[p["side"]], "entry_time": p["entry_time"],
                        "entry_raw": p["entry_raw"], "stop": p["stop"], "target": p["target"],
                        "age": p["age"], "levels_source": p["levels_source"],
                        "breakeven": p["entry_raw"] * math.exp(p["side"] * s.hurdle(p["side"], s.horizon_minutes or 30)),
                        "best_pct": p["side"] * math.log(p["best"] / p["entry_raw"]),
                        "worst_pct": p["side"] * math.log(p["worst"] / p["entry_raw"]),
                        "gross_display": open_gross * to_display, "net_display": open_net * to_display,
                        "net_pct": open_net / p["stake_quote"]}
        return self._event("equity", bar.open_time, balance_display=self.realized_display,
                           marked_display=self.realized_display + (open_net or 0.0) * to_display,
                           buy_hold_display=baseline, rate=rate, position=position)
