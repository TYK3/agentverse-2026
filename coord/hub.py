"""Run with: uvicorn coord.hub:app --port 8000 --reload."""

import asyncio
import importlib
import inspect
import json
import logging
import os
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
