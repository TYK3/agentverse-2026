"""Run with: uvicorn coord.hub:app --port 8000 --reload."""

import asyncio
import importlib
import inspect
import json
import logging
import multiprocessing
import os
import queue
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

# HUB-PROCESSES: with HUB_PROCESSES=1 the lanes named here run in their own process, so a slow planner or
# perception callback on the hub's event loop cannot stall the sim's 10 Hz tick. Off by default.
PROCESS_LANES = ("sim",)
PROCESS_READY_S = 120.0     # a lane process has this long to load (MuJoCo scene) and call its start(bus)
PROCESS_STOP_S = 5.0


def processes_enabled(env=None):
    return (os.environ if env is None else env).get("HUB_PROCESSES", "") == "1"


class ProxyBus:
    """The bus a lane sees inside its own process: subscribe/publish go over queues to the hub's Bus.

    publish() returns at once (the hub validates and delivers the message); subscribe() asks the hub to
    forward that topic here, where this process's own subscribers run in subscription order, one message
    at a time, exactly as the hub's Bus runs them.
    """

    def __init__(self, outbox):
        self.outbox = outbox
        self.subs = defaultdict(list)

    def subscribe(self, topic, fn):
        if not self.subs[topic]:
            self.outbox.put(("sub", topic))
        self.subs[topic].append(fn)

    async def publish(self, topic, data):
        self.outbox.put(("pub", topic, data))

    async def deliver(self, topic, data):
        for fn in tuple(self.subs.get(topic, ())):
            try:
                result = fn(data)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                log.exception("Subscriber failed for %s (lane process)", topic)


async def _queue_get(q, timeout=0.25):
    """One item from a multiprocessing queue without blocking the event loop, or None after `timeout`."""
    try:
        return await asyncio.get_running_loop().run_in_executor(None, q.get, True, timeout)
    except queue.Empty:
        return None


def _lane_process_main(name, inbox, outbox):
    """Entry point of a lane process (spawned): start the lane on a ProxyBus and serve the hub's messages."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_lane_process(name, inbox, outbox))


async def _lane_process(name, inbox, outbox):
    proxy = ProxyBus(outbox)
    try:
        lane = importlib.import_module(name)
        world = await lane.start(proxy)
    except Exception as exc:  # noqa: BLE001 - reported to the hub, which logs and carries on without it
        outbox.put(("failed", f"{type(exc).__name__}: {exc}"))
        return
    outbox.put(("ready",))
    try:
        while True:
            item = await _queue_get(inbox)
            if item is None:
                continue
            if item[0] == "stop":
                break
            if item[0] == "msg":
                await proxy.deliver(item[1], item[2])
            elif item[0] == "inject":       # POST /inject, answered by the lane's world (sim/inject.py)
                from sim import inject
                status, body = inject.handle(world, item[2])
                outbox.put(("inject", item[1], status, body))
    finally:
        task = getattr(world, "task", None)
        if isinstance(task, asyncio.Task):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


class LaneProcess:
    """The hub side of a lane running in its own process (HUB_PROCESSES=1)."""

    def __init__(self, name, target_bus):
        ctx = multiprocessing.get_context("spawn")     # fork + asyncio + MuJoCo is not safe; spawn is
        self.name, self.bus = name, target_bus
        self.inbox, self.outbox = ctx.Queue(), ctx.Queue()
        self.process = ctx.Process(target=_lane_process_main, args=(name, self.inbox, self.outbox),
                                   name=f"lane-{name}", daemon=True)
        self.forwarded = set()
        self.replies = {}
        self.task = None
        self._next = 0

    def _forward(self, topic):
        async def forward(data):
            self.inbox.put(("msg", topic, data))
        return forward

    async def _handle(self, item):
        kind = item[0]
        if kind == "sub" and item[1] not in self.forwarded:
            self.forwarded.add(item[1])
            self.bus.subscribe(item[1], self._forward(item[1]))
        elif kind == "pub":
            try:
                await self.bus.publish(item[1], item[2])
            except Exception:
                log.exception("Lane %s published an invalid %s", self.name, item[1])
        elif kind == "inject":
            future = self.replies.pop(item[1], None)
            if future is not None and not future.done():
                future.set_result((item[2], item[3]))

    async def start(self, ready_s=PROCESS_READY_S):
        """Spawn the process and relay its messages until it says ready. Returns False if it failed."""
        self.process.start()
        end = asyncio.get_running_loop().time() + ready_s
        while asyncio.get_running_loop().time() < end:
            item = await _queue_get(self.outbox)
            if item is None:
                if not self.process.is_alive():
                    break
                continue
            if item[0] == "ready":
                self.task = asyncio.create_task(self._relay())
                return True
            if item[0] == "failed":
                log.error("Lane %s process failed to start: %s", self.name, item[1])
                break
            await self._handle(item)
        await self.stop()
        return False

    async def _relay(self):
        while True:
            item = await _queue_get(self.outbox)
            if item is not None:
                await self._handle(item)

    async def inject(self, body, timeout=10.0):
        self._next += 1
        future = asyncio.get_running_loop().create_future()
        self.replies[self._next] = future
        self.inbox.put(("inject", self._next, body))
        try:
            return await asyncio.wait_for(future, timeout)
        except TimeoutError:
            self.replies.pop(self._next, None)
            return 504, {"error": f"{self.name} process did not answer"}

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        if self.process.is_alive():
            self.inbox.put(("stop",))
            await asyncio.get_running_loop().run_in_executor(None, self.process.join, PROCESS_STOP_S)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(PROCESS_STOP_S)


def _install_process_inject(lane):
    """POST /inject answered by the sim world in its process (the in-process sim adds its own route)."""
    async def inject(request: Request):
        try:
            body = await request.json()
        except ValueError:
            body = None
        status, reply = await lane.inject(body)
        return JSONResponse(reply, status_code=status)

    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/inject"]
    app.add_api_route("/inject", inject, methods=["POST"])


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
    processes = []
    try:
        points = PointCloudPublisher(bus)
        tasks.append(asyncio.create_task(points.run()))
        for name in LANES:
            if processes_enabled() and name in PROCESS_LANES:
                lane_process = LaneProcess(name, bus)
                if await lane_process.start():
                    processes.append(lane_process)
                    if name == "sim":
                        _install_process_inject(lane_process)
                else:
                    log.warning("Lane %s process did not start; running without it", name)
                continue
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
        for lane_process in processes:
            await lane_process.stop()
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
