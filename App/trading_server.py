"""Interface local de operação simulada: replay do histórico ou paper trading ao vivo.

Exemplos, na raiz do projeto:
  python App/trading_server.py replay --start 2025-11-20 --end 2025-11-27
  python App/trading_server.py live
Abre http://127.0.0.1:8000. Nenhuma ordem real é enviada.
"""

import argparse
import asyncio
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
import time
import webbrowser

from trading_engine import Engine, Settings, performance
from trading_models import MODELS
from trading_sources import FxSeries, epoch, iso, live_bars, read_history

HERE = Path(__file__).resolve().parent
INTERFACE = HERE / "interface"


class EventLog:
    """Log somente acréscimo em SQLite; cada sessão pode ser auditada e reproduzida."""

    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        # WAL: uma gravação por candle sem esperar o disco a cada commit; sobrevive a queda do processo.
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, "
                        "time INTEGER NOT NULL, recorded_utc TEXT NOT NULL, payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS session (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.execute("CREATE TRIGGER IF NOT EXISTS append_only BEFORE UPDATE ON events "
                        "BEGIN SELECT RAISE(ABORT, 'log somente acréscimo'); END")
        self.db.execute("CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON events "
                        "BEGIN SELECT RAISE(ABORT, 'log somente acréscimo'); END")
        self.db.commit()

    def describe(self, session):
        with self.lock:
            self.db.executemany("INSERT OR REPLACE INTO session VALUES (?, ?)",
                                [(key, json.dumps(value, ensure_ascii=False)) for key, value in session.items()])
            self.db.commit()

    def append(self, events):
        stamped = []
        recorded = datetime.now(timezone.utc).isoformat()
        with self.lock:
            for event in events:
                payload = json.dumps(event, ensure_ascii=False, allow_nan=False)
                cursor = self.db.execute("INSERT INTO events (kind, time, recorded_utc, payload) VALUES (?, ?, ?, ?)",
                                         (event["kind"], event["time"], recorded, payload))
                stamped.append({"seq": cursor.lastrowid, **event})
            self.db.commit()
        return stamped

    def since(self, after=0, limit=50000):
        with self.lock:
            rows = self.db.execute("SELECT id, payload FROM events WHERE id > ? ORDER BY id LIMIT ?",
                                   (after, limit)).fetchall()
        return [{"seq": row[0], **json.loads(row[1])} for row in rows]


def split_overlap(start, end, boundaries):
    """Divisões do dataset que o intervalo [start, end) toca, pelas fronteiras do manifesto."""
    touched = []
    for name, limits in boundaries.items():
        first, last = epoch(limits["first_start_utc"]), epoch(limits["last_available_at_utc"])
        if start < last and end > first:
            touched.append(name)
    if not boundaries or end > max(epoch(v["last_available_at_utc"]) for v in boundaries.values()):
        touched.append("fora_do_dataset")
    return touched


def prediction_quality(outcomes):
    """Erro da previsão contra a previsão zero, nas mesmas decisões já resolvidas."""
    if not outcomes:
        return {"resolved": 0}
    n = len(outcomes)
    mae = sum(abs(o["error"]) for o in outcomes) / n
    mae_zero = sum(abs(o["realized"]) for o in outcomes) / n
    signs = [o for o in outcomes if o["predicted"] != 0 and o["realized"] != 0]
    hits = sum((o["predicted"] > 0) == (o["realized"] > 0) for o in signs)
    return {"resolved": n, "mae": mae, "mae_zero_forecast": mae_zero,
            "direction_accuracy": hits / len(signs) if signs else None}


class Runner:
    def __init__(self, engine, log, session):
        self.engine, self.log, self.session = engine, log, session
        self.lock = threading.Lock()
        self.subscribers = set()
        self.loop = None
        self.paused = session["mode"] == "replay"
        self.steps = 0
        self.speed = session.get("speed", 60)
        self.finished = False
        self.outcomes = []
        self.status = "aguardando"
        log.describe(session)

    def process(self, bar, received=None, warmup=False):
        with self.lock:
            self.engine.warming = warmup
            events = self.engine.on_bar(bar)
            self.outcomes += [e for e in events if e["kind"] == "outcome"]
        if received is not None:
            events[0]["latency_seconds"] = received - (bar.open_time + 60)
        return events

    def commit(self, events):
        if events:
            self.publish(self.log.append(events))

    def feed(self, bar, received=None, warmup=False):
        self.commit(self.process(bar, received, warmup))

    def publish(self, stamped):
        if self.loop is None:
            return
        for queue in list(self.subscribers):
            self.loop.call_soon_threadsafe(queue.put_nowait, stamped)

    def notice(self, message, level="info", code="status"):
        self.status = message
        previous = self.engine.previous
        # No replay, o horário do aviso é o do último candle simulado, não o relógio real.
        moment = previous.open_time + 60 if previous and self.session["mode"] == "replay" else int(time.time()) // 60 * 60
        self.publish(self.log.append([{"kind": "alert", "time": moment,
                                       "level": level, "code": code, "message": message}]))

    def replay(self, bars):
        # Em velocidade alta, grava e transmite em lotes de ~50 ms em vez de candle a candle.
        pending, flushed = [], time.monotonic()
        for bar in bars:
            while self.paused and self.steps == 0:
                self.commit(pending)
                pending = []
                time.sleep(.05)
            if self.steps:
                self.steps -= 1
            elif self.speed:
                time.sleep(60 / self.speed)
            pending += self.process(bar)
            fast = not self.speed or self.speed > 1200
            if fast and time.monotonic() - flushed < .05:
                continue  # passos manuais são gravados no laço de pausa acima
            self.commit(pending)
            pending, flushed = [], time.monotonic()
        self.commit(pending)
        self.finished = True
        self.notice("Replay concluído", code="finished")

    def control(self, action, value=None):
        if action == "pause":
            self.paused = True
        elif action == "resume":
            self.paused = False
        elif action == "step":
            self.steps += max(1, int(value or 1))
        elif action == "speed":
            self.speed = max(0.0, float(value))
        else:
            raise ValueError("Ação desconhecida")
        return {"paused": self.paused, "speed": self.speed}


def create_app(runner, background=None):
    """background: corrotina opcional iniciada com o servidor (fonte ao vivo)."""
    from contextlib import asynccontextmanager
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    @asynccontextmanager
    async def lifespan(_):
        runner.loop = asyncio.get_running_loop()
        task = asyncio.create_task(background()) if background else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="QuantLab simulação", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=INTERFACE), name="static")

    @app.get("/")
    def index():
        return FileResponse(INTERFACE / "index.html")

    @app.get("/api/session")
    def session():
        return {**runner.session, "paused": runner.paused, "speed": runner.speed,
                "finished": runner.finished, "status": runner.status}

    @app.get("/api/events")
    def events(after: int = 0, limit: int = 50000):
        return runner.log.since(after, min(limit, 50000))

    @app.get("/api/stats")
    def stats():
        with runner.lock:
            trades = list(runner.engine.trades)
        return {"trading": performance(trades), "prediction": prediction_quality(runner.outcomes)}

    @app.post("/api/control")
    def control(command: dict):
        if runner.session["mode"] != "replay":
            raise HTTPException(400, "Controles de velocidade existem só no replay")
        try:
            return runner.control(command.get("action"), command.get("value"))
        except (TypeError, ValueError) as error:
            raise HTTPException(400, str(error)) from error

    @app.websocket("/ws")
    async def stream(socket: WebSocket, after: int = 0):
        await socket.accept()
        queue = asyncio.Queue()
        runner.subscribers.add(queue)
        try:
            last = after
            while True:
                backlog = runner.log.since(last, 20000)
                if not backlog:
                    break
                await socket.send_text(json.dumps(backlog, ensure_ascii=False))
                last = backlog[-1]["seq"]
            while True:
                batch = [event for event in await queue.get() if event["seq"] > last]
                if batch:
                    await socket.send_text(json.dumps(batch, ensure_ascii=False))
                    last = batch[-1]["seq"]
        except WebSocketDisconnect:
            pass
        finally:
            runner.subscribers.discard(queue)

    return app


def build_settings(args):
    return Settings(stake=args.stake, fee_bps=args.fee_bps, slippage_bps=args.slippage_bps,
                    allow_short=not args.no_short, borrow_bps_per_hour=args.borrow_bps_hora,
                    horizon_minutes=args.horizon or None,
                    levels=not args.no_stops, stop_k=args.stop_k, target_k=args.target_k)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("replay", "live"))
    parser.add_argument("--model", choices=sorted(MODELS), default="cnn")
    parser.add_argument("--data", type=Path, default=HERE / "data" / "bitcoin")
    parser.add_argument("--start", type=date.fromisoformat, help="Data UTC inicial do replay")
    parser.add_argument("--end", type=date.fromisoformat, help="Data UTC final exclusiva do replay")
    parser.add_argument("--allow-test", action="store_true", help="Permite replay no teste; fica registrado na sessão")
    parser.add_argument("--speed", type=float, default=60, help="Múltiplo do tempo real; 0 = máximo")
    parser.add_argument("--stake", type=float, default=50)
    parser.add_argument("--fx-csv", type=Path, help="Histórico USDTBRL com timestamp e close para converter em reais")
    parser.add_argument("--usdtbrl-fixo", type=float, help="Cotação fixa hipotética; marcada como tal na tela")
    parser.add_argument("--sem-brl", action="store_true", help="Ao vivo: exibir em USDT")
    parser.add_argument("--fee-bps", type=float, default=10)
    parser.add_argument("--slippage-bps", type=float, default=5)
    parser.add_argument("--borrow-bps-hora", type=float, default=.1)
    parser.add_argument("--horizon", type=int, default=30, help="Minutos até a saída por tempo; 0 desliga")
    parser.add_argument("--stop-k", type=float, default=2)
    parser.add_argument("--target-k", type=float, default=2)
    parser.add_argument("--no-stops", action="store_true")
    parser.add_argument("--no-short", action="store_true")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    settings = build_settings(args)
    try:
        settings.validate()
    except ValueError as error:
        parser.error(str(error))
    model = MODELS[args.model]()
    created = datetime.now(timezone.utc)
    session = {"mode": args.mode, "model": model.name, "model_version": model.version,
               "model_description": model.description, "settings": settings.__dict__,
               "created_utc": created.isoformat(), "simulation_only": True, "speed": args.speed}
    fx = None
    if args.mode == "replay":
        if not args.start or not args.end or args.start >= args.end:
            parser.error("Replay exige --start e --end, com início antes do fim")
        start = int(datetime.combine(args.start, datetime.min.time(), timezone.utc).timestamp())
        end = int(datetime.combine(args.end, datetime.min.time(), timezone.utc).timestamp())
        manifest = json.loads((args.data / "manifest.json").read_text(encoding="utf-8"))
        touched = split_overlap(start, end, manifest["quality"]["split_boundaries"])
        if "test" in touched and not args.allow_test:
            parser.error("O período toca o teste. Olhar o teste repetidamente o transforma em validação; "
                         "use --allow-test somente para a avaliação final")
        session.update(start_utc=iso(start), end_utc=iso(end), splits=touched, test_unlocked=args.allow_test)
        if args.fx_csv:
            fx = FxSeries(args.fx_csv)
            session["currency"], session["fx_source"] = "BRL", f"USDTBRL histórico: {args.fx_csv.name}"
        elif args.usdtbrl_fixo:
            fx = FxSeries(fixed=args.usdtbrl_fixo)
            session["currency"], session["fx_source"] = "BRL", f"Cotação fixa hipotética {args.usdtbrl_fixo}"
        else:
            session["currency"], session["fx_source"] = "USDT", "Sem câmbio: valores em USDT"
    else:
        if args.sem_brl:
            session["currency"], session["fx_source"] = "USDT", "Sem câmbio: valores em USDT"
        else:
            fx = FxSeries()
            session["currency"], session["fx_source"] = "BRL", "USDTBRL ao vivo da Binance"
    database = args.db or HERE / "results" / "sessions" / f"{created:%Y%m%dT%H%M%SZ}_{args.mode}.sqlite"
    runner = Runner(Engine(model, settings, fx), EventLog(database), session)
    background = None
    if args.mode == "replay":
        threading.Thread(target=runner.replay, args=(read_history(args.data / "btc_usdt_1m.csv", start, end),),
                         daemon=True).start()
    else:
        async def background():
            await live_bars("BTCUSDT", lambda bar, warmup: runner.feed(bar, time.time(), warmup),
                            on_fx=None if args.sem_brl else (lambda bar: fx.add(bar.open_time, bar.close)),
                            on_status=lambda message: runner.notice(message, code="connection"))
    app = create_app(runner, background)
    import uvicorn
    url = f"http://127.0.0.1:{args.port}"
    print(f"Interface: {url}\nLog da sessão: {database}", flush=True)
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, (url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
