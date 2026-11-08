"""Run with: uvicorn coord.hub:app --port 8000 --reload."""

import asyncio
import importlib
import inspect
import json
import logging
import os
import pathlib
import tempfile
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from coord.messages import Envelope, validate_payload
from coord.points import PointCloudPublisher

log = logging.getLogger(__name__)
LANES = ("sim", "perception", "planner", "voice")
BROWSER_TOPICS = {"operator/command", "gate/answer", "status/link"}
LATEST_TOPICS = {"map/points"}
# LIVE-UI: the console dev server (vite, port 5173) may call the hub's HTTP routes, such as
# POST /inject. HUB_CORS_ORIGINS="http://a:5173,http://b:5173" adds origins (a LAN address).
CONSOLE_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
INJECT_KINDS = ("aftershock", "block_added")
RUN_FLOORS = ("B1", "B2", "B3")
RUN_IDLE = {"state": "idle", "floor": None, "t": 0.0, "log": None, "verdict": None}
_run_status = RUN_IDLE.copy()
_run_task = None


class Bus:
    def __init__(self):
        self.subs = defaultdict(list)
        self.clients = set()
        self.history = deque(maxlen=200)
        self.latest = {}  # large frame topics keep only their latest bounded message
        self._delivery_lock = asyncio.Lock()

    def subscribe(self, topic, fn):
        self.subs[topic].append(fn)

    async def publish(self, topic, data):
        data = validate_payload(topic, data)
        # Deliver before callbacks: a callback may recursively publish a response.
        if topic != "sensors/scout":
            msg = {"topic": topic, "data": data}
            async with self._delivery_lock:
                if topic == "scene/loaded":
                    self.latest.pop("map/points", None)
                if topic in LATEST_TOPICS:
                    self.latest[topic] = msg
                else:
                    self.history.append(msg)
                for client in tuple(self.clients):
                    try:
                        await client.send_text(json.dumps(msg, allow_nan=False))
                    except Exception:
                        log.debug("Dropping disconnected browser client", exc_info=True)
                        self.clients.discard(client)
        for fn in tuple(self.subs[topic]):
            try:
                result = fn(data)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                log.exception("Subscriber failed for %s", topic)

    async def connect(self, websocket):
        # Replay and registration are atomic relative to live delivery.
        async with self._delivery_lock:
            for msg in self.history:
                await websocket.send_text(json.dumps(msg))
            for msg in self.latest.values():
                await websocket.send_text(json.dumps(msg))
            self.clients.add(websocket)


bus = Bus()


async def publish_checked(topic, data):
    await bus.publish(topic, data)


async def publish_gemini_status(target_bus, gem, interval=2):
    forwarded = set()
    while True:
        await target_bus.publish("status/gemini", gem.status())
        try:
            history = getattr(gem, "receipts", list)()
            current = set()
            for receipt in history:
                try:
                    call_id = receipt["id"]
                    if not isinstance(call_id, str) or not call_id:
                        raise ValueError("invalid receipt ID")
                    current.add(call_id)
                    if call_id not in forwarded:
                        await target_bus.publish("gemini/receipt", receipt)
                        forwarded.add(call_id)  # only successful deliveries are deduplicated
                except Exception as exc:  # noqa: BLE001 - isolate optional telemetry without logging private exception text
                    log.warning("Gemini receipt delivery skipped (%s); will retry", type(exc).__name__)
            # Bound deduplication to the current ring, retaining it if a snapshot fails.
            forwarded.intersection_update(current)
        except Exception as exc:  # noqa: BLE001 - optional provider snapshots must not kill the status loop
            log.warning("Gemini receipt snapshot skipped (%s); will retry", type(exc).__name__)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(application):
    global _run_status, _run_task
    _run_status, _run_task = RUN_IDLE.copy(), None
    tasks = []
    try:
        points = PointCloudPublisher(bus)
        tasks.append(asyncio.create_task(points.run()))
        for name in LANES:
            try:
                lane = importlib.import_module(name)
            except ModuleNotFoundError as exc:
                if exc.name != name:
                    raise
                log.warning("Lane %s is not installed; skipping", name)
                continue
            start = getattr(lane, "start", None)
            if start is None:
                log.warning("Lane %s has no start(bus); skipping", name)
                continue
            # start(bus) wires subscriptions and launches background work, then returns.
            result = await start(bus)
            if isinstance(result, asyncio.Task):
                tasks.append(result)
            elif isinstance(result, (list, tuple)):
                tasks.extend(task for task in result if isinstance(task, asyncio.Task))
            elif isinstance(getattr(result, "task", None), asyncio.Task):
                tasks.append(result.task)
        try:
            gem = importlib.import_module("coord.gem")
        except ModuleNotFoundError as exc:
            if exc.name != "coord.gem":
                raise
            log.warning("coord.gem is not installed; status/gemini publisher skipped")
        else:
            tasks.append(asyncio.create_task(publish_gemini_status(bus, gem)))
        yield
    finally:
        if _run_task is not None:
            _run_task.cancel()
            await asyncio.gather(_run_task, return_exceptions=True)
        _run_status, _run_task = RUN_IDLE.copy(), None
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        bus.subs.clear()


def cors_origins(env=None):
    extra = (os.environ if env is None else env).get("HUB_CORS_ORIGINS", "")
    added = [origin.strip() for origin in extra.split(",")]
    return CONSOLE_ORIGINS + [origin for origin in added if origin and origin != "*"]


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)


def run_status():
    """A snapshot with the shape shared by POST /run/rescue and GET /run."""
    return {**_run_status, "verdict": _run_status["verdict"] and dict(_run_status["verdict"])}


async def publish_run_record(target_bus, record):
    """Forward one canonical JSONL record through the existing validated decision-log topic."""
    await target_bus.publish("log/decision", {
        "t": record["t"], "perception": f"chained rescue {record.get('leg', '')}".strip(),
        "model": "tools/run_chain.py", "physics": "MuJoCo simulation",
        "outcome": record["kind"], "reason": json.dumps(record, separators=(",", ":"), allow_nan=False),
    })


async def run_rescue_worker(seed, floors, runner, target_bus, out):
    """Run each real leg in a worker thread; publish its records before starting the next leg."""
    global _run_task
    from tools import run_b2

    try:
        legs, offset = [], 0.0
        await publish_run_record(target_bus, {
            "t": 0.0, "kind": "meta", "seed": seed, "legs": list(floors), "source": "tools/run_chain.py",
        })
        with tempfile.TemporaryDirectory() as temp:
            for floor in floors:
                _run_status["floor"] = floor
                verdict, path = await asyncio.to_thread(
                    run_b2.run, seed=seed, max_t=500.0, out_dir=temp, verbose=False, floor=floor,
                )
                records = runner.leg_records(path)
                legs.append((floor, records, verdict))
                end = max((record.get("t") or 0.0 for record in records), default=0.0)
                for record in records:
                    kind = "leg_summary" if record["kind"] == "summary" else record["kind"]
                    await publish_run_record(target_bus, {
                        **record, "kind": kind, "t": round(offset + (record.get("t") or 0.0), 2),
                        "leg_t": record.get("t"), "leg": floor,
                    })
                offset = round(offset + end, 2)
                _run_status["t"] = offset
                await publish_run_record(target_bus, {
                    "t": offset, "kind": "leg", "floor": floor, "casualty": runner.CASUALTY[floor],
                    "reached": bool(next((r for r in records if r["kind"] == "summary"), {}).get("reached")),
                    "passed": len(verdict["passed"]), "failed": len(verdict["failed"]),
                })
        canonical = runner.chain(legs, seed)
        out.write_text("".join(json.dumps(r, separators=(",", ":"), allow_nan=False) + "\n"
                               for r in canonical), encoding="utf-8")
        for record in canonical:
            if record["kind"] in {"step", "summary"}:
                await publish_run_record(target_bus, record)
        passed = [f"{floor}: {name}" for floor, _, verdict in legs for name in verdict["passed"]]
        failed = [f"{floor}: {name}" for floor, _, verdict in legs for name in verdict["failed"]]
        _run_status.update(state="failed" if failed else "done", floor=floors[-1],
                           t=canonical[-1]["t"], verdict={"passed": passed, "failed": failed})
    except Exception:
        log.exception("Chained rescue run failed")
        out.write_text(json.dumps({"t": _run_status["t"], "kind": "error", "reason": "runner error"}) + "\n",
                       encoding="utf-8")
        _run_status.update(state="failed", verdict={"passed": [], "failed": ["runner error"]})
    finally:
        _run_task = None


@app.get("/run")
async def get_run():
    return run_status()


@app.post("/run/rescue")
async def start_rescue_run(request: Request):
    global _run_status, _run_task
    if _run_status["state"] == "running":
        return JSONResponse({"error": "rescue run already running"}, status_code=409)
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else {}
    except (ValueError, RecursionError):
        body = None
    if not isinstance(body, dict) or set(body) - {"seed", "floors"}:
        return JSONResponse({"error": "expected seed and floors"}, status_code=400)
    seed = body.get("seed", 0)
    floors = body.get("floors", list(RUN_FLOORS))
    if (type(seed) is not int or not 0 <= seed <= 1_000_000 or not isinstance(floors, list)
            or not floors or any(floor not in RUN_FLOORS for floor in floors)
            or tuple(floors) != tuple(floor for floor in RUN_FLOORS if floor in floors)):
        return JSONResponse({"error": "invalid seed or floors"}, status_code=400)
    try:
        runner = importlib.import_module("tools.run_chain")
    except ModuleNotFoundError as exc:
        if exc.name != "tools.run_chain":
            raise
        return JSONResponse({"error": "chained rescue runner unavailable"}, status_code=503)
    # Request-body reads yield to the event loop, so recheck after validation before claiming the run.
    if _run_status["state"] == "running":
        return JSONResponse({"error": "rescue run already running"}, status_code=409)
    out = pathlib.Path("runs") / f"chain-{seed}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("", encoding="utf-8")
    _run_status = {"state": "running", "floor": floors[0], "t": 0.0,
                   "log": out.as_posix(), "verdict": None}
    _run_task = asyncio.create_task(run_rescue_worker(seed, floors, runner, bus, out))
    return JSONResponse(run_status(), status_code=202)


@app.post("/inject")
async def inject_without_sim(request: Request):
    """Stand-in for the sim's POST /inject (sim/inject.py), which replaces this route when the sim
    lane runs on the hub. Without a live sim it answers 503 instead of 404, so the console can fall
    back to its local demo. It never publishes: world/change only comes from the sim."""
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or body.get("kind") not in INJECT_KINDS:
        return JSONResponse({"error": "kind must be block_added or aftershock"}, status_code=400)
    return JSONResponse({"error": "no live sim on this hub"}, status_code=503)


@app.websocket("/ws")
async def websocket_gateway(websocket: WebSocket):
    await websocket.accept()
    try:
        await bus.connect(websocket)
        while True:
            raw = await websocket.receive_text()
            try:
                message = Envelope.model_validate_json(raw, strict=True)
                if message.topic not in BROWSER_TOPICS:
                    raise ValueError("topic is not writable by browser clients")
                data = validate_payload(message.topic, message.data)
            except (ValueError, TypeError):
                await websocket.close(code=1008)
                return
            await publish_checked(message.topic, data)
    except WebSocketDisconnect:
        pass
    finally:
        bus.clients.discard(websocket)
