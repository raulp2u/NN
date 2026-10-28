"""Fontes de candles fechados: histórico local para replay e Binance pública para paper trading."""

import asyncio
from bisect import bisect_right
import csv
from datetime import datetime, timezone
import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from trading_engine import MINUTE, Bar

STREAM = "wss://stream.binance.com:9443/stream?streams="
REST = "https://api.binance.com/api/v3/klines"


def epoch(text):
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def read_history(path, start, end):
    """Candles com abertura em [start, end), do CSV normalizado timestamp,open,high,low,close,volume."""
    with open(path, encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            moment = epoch(row["timestamp"])
            if moment < start:
                continue
            if moment >= end:
                return
            yield Bar(moment, *(float(row[key]) for key in ("open", "high", "low", "close", "volume")))


class FxSeries:
    """Cotação causal: fechamento do último candle já encerrado no instante pedido."""

    def __init__(self, path=None, fixed=None, max_age_minutes=5):
        self.fixed = fixed
        self.times, self.values = [], []
        self.max_age = max_age_minutes * MINUTE
        if path:
            with open(path, encoding="utf-8", newline="") as stream:
                for row in csv.DictReader(stream):
                    self.add(epoch(row["timestamp"]), float(row["close"]))

    def add(self, open_time, close):
        if self.times and open_time <= self.times[-1]:
            return
        self.times.append(open_time)
        self.values.append(close)

    def __call__(self, moment):
        if self.fixed is not None:
            return self.fixed
        index = bisect_right(self.times, moment - MINUTE) - 1
        if index < 0 or moment - (self.times[index] + MINUTE) > self.max_age:
            return None
        return self.values[index]


def parse_kline_message(message):
    """Mensagem do stream combinado da Binance; retorna (símbolo, Bar) só para candle fechado."""
    data = json.loads(message) if isinstance(message, (str, bytes)) else message
    data = data.get("data", data)
    if data.get("e") != "kline":
        return None
    k = data["k"]
    if not k["x"] or k["i"] != "1m":
        return None
    return k["s"], Bar(int(k["t"]) // 1000, float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]), float(k["v"]))


def fetch_closed(symbol, start, end, now=None):
    """Candles fechados com abertura em [start, end) pela API REST pública, sem chave."""
    now = time.time() if now is None else now
    bars = []
    while start < end:
        query = urlencode({"symbol": symbol, "interval": "1m", "startTime": start * 1000,
                           "endTime": (end - 1) * 1000, "limit": 1000})
        with urlopen(Request(f"{REST}?{query}", headers={"User-Agent": "QuantLab-paper/1.0"}), timeout=30) as source:
            rows = json.load(source)
        if not rows:
            break
        for row in rows:
            if row[6] / 1000 < now:
                bars.append(Bar(int(row[0]) // 1000, *(float(x) for x in row[1:6])))
        start = int(rows[-1][0]) // 1000 + MINUTE
    return bars


async def live_bars(symbol, on_bar, on_fx=None, fx_symbol="USDTBRL", warmup=60, on_status=None):
    """Assina candles de 1 minuto; preenche lacunas por REST ao reconectar. Nunca usa candle aberto.
    on_bar(bar, warmup): warmup verdadeiro para o histórico inicial, que não deve gerar ordens."""
    import websockets
    streams = [f"{symbol.lower()}@kline_1m"] + ([f"{fx_symbol.lower()}@kline_1m"] if on_fx else [])
    last = None
    now = int(time.time()) // MINUTE * MINUTE
    for bar in await asyncio.to_thread(fetch_closed, symbol, now - warmup * MINUTE, now):
        on_bar(bar, True)
        last = bar.open_time
    if on_fx:
        for bar in await asyncio.to_thread(fetch_closed, fx_symbol, now - 10 * MINUTE, now):
            on_fx(bar)
    delay = 1
    while True:
        try:
            async with websockets.connect(STREAM + "/".join(streams), ping_interval=20) as socket:
                if on_status:
                    on_status("conectado")
                delay = 1
                async for message in socket:
                    parsed = parse_kline_message(message)
                    if parsed is None:
                        continue
                    name, bar = parsed
                    if name == fx_symbol and on_fx:
                        on_fx(bar)
                        continue
                    if last is not None and bar.open_time <= last:
                        continue
                    if last is not None and bar.open_time - last > MINUTE:
                        for missing in await asyncio.to_thread(fetch_closed, symbol, last + MINUTE, bar.open_time):
                            on_bar(missing, False)
                            last = missing.open_time
                    on_bar(bar, False)
                    last = bar.open_time
        except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as error:
            if on_status:
                on_status(f"desconectado: {error}; nova tentativa em {delay}s")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)
