"""HUB-SOAK: real local TCP, synthetic world/sensors, actual hub and sim inject handler.

Normal CI executes a short run. For the full ten minutes:
GEMINI_MODE=off HUB_SOAK_SECONDS=600 python -m pytest coord/tests/test_hub_soak.py -q -s
Metrics go to local runs/hub-soak-<seconds>s.json; no physics/rescue claim is made.
"""

import asyncio
import hashlib
import json
import math
import os
import socket
import threading
import time
from collections import Counter, deque
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from websockets.asyncio.client import connect

from coord import gem, hub
from coord.tests.test_inject_cors import CONSOLE, INJECT_PY, _sim_inject


class SyntheticWorld:
    def __init__(self):
        self.pending = deque()
        self.serial = 0
        self.marker = None
        self.injections = Counter()
        self.answers = 0
        self.commands = 0

    def changed(self, kind):
        self.serial += 1
        self.marker = f"soak-block-{self.serial}"
        self.pending.append((kind, self.marker, self.serial))
        self.injections[kind] += 1

    def add_block(self, _):
        self.changed("block_added")
        return self.marker

    def trigger_aftershock(self):
        self.changed("aftershock")
        return True

    def answer(self, _):
        self.answers += 1

    def command(self, _):
        self.commands += 1

    async def pump(self, target):
        began, tick = time.monotonic(), 0
        points = [[(i % 32) * 0.1 + 0.013, (i // 32) * 0.1 + 0.027, -1.2] for i in range(2048)]
        await target.publish("scene/loaded", {"scene": "backup", "blocks": []})
        # Overflow event history before the first connection, so even the short run tests bounded replay.
        for index in range(205):
            await target.publish("log/decision", {"t": 0, "perception": "synthetic startup",
                "model": "soak-stub", "physics": "not a physics run", "outcome": "ready", "reason": str(index)})
        while True:
            now = time.monotonic() - began
            frame = {"t": now, "pose": {"pos": [0, 0, -1.2], "yaw": 0}, "lidar": [1.0],
                     "thermal": [[0.2]], "acoustic": {"bearing": 0, "level": 0.1},
                     "camera": {"format": "jpeg", "b64": "private-soak-camera"}}
            if tick % 5 == 0:
                frame.update(points=points, points_from=[0, 0, -1.0])
            await target.publish("sensors/scout", frame)
            await target.publish("responder/pose", {"t": now, "pos": [0, 0, -1.2], "yaw": 0,
                                                    "state": "idle", "route": None, "carrying": []})
            while self.pending:
                kind, marker, serial = self.pending.popleft()
                await target.publish("world/change", {"kind": kind, "t": now, "moved_blocks": [marker]})
                await target.publish("gate/request", {"id": f"soak-gate-{serial}", "kind": "risky_move",
                    "summary": "synthetic transport gate", "route": f"soak-route-{serial}"})
            tick += 1
            await asyncio.sleep(0.1)


async def exercise(port, duration, target, world):
    began, cycles = time.monotonic(), 0
    observed = Counter()
    peaks = {"history": 0, "clouds": 0, "clients": 0, "cloud_points": 0}

    async def receive_until(browser, predicate):
        deadline = time.monotonic() + 10
        while True:
            remaining = deadline - time.monotonic()
            assert remaining > 0, "hub event deadline exceeded"
            raw = await asyncio.wait_for(browser.recv(), remaining)
            assert "private-soak-camera" not in raw
            message = json.loads(raw)
            topic, data = message["topic"], message["data"]
            assert topic != "sensors/scout"
            observed[topic] += 1
            if topic == "map/points":
                assert len(data["points"]) <= 2048
                peaks["cloud_points"] = max(peaks["cloud_points"], len(data["points"]))
            if predicate(topic, data):
                return data

    next_progress = 30.0
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=10) as http:
        while time.monotonic() - began < duration or cycles < 2:
            async with connect(f"ws://127.0.0.1:{port}/ws", proxy=None, max_size=2**20,
                               open_timeout=10, close_timeout=5) as browser:
                await receive_until(browser, lambda topic, _: topic == "map/points")
                kind = "aftershock" if cycles % 2 else "block_added"
                body = {"kind": kind, "pos": [0.3, 0.2, -1.1]} if kind == "block_added" else {"kind": kind}
                try:
                    reply = await http.post("/inject", json=body, headers={"Origin": CONSOLE})
                except httpx.HTTPError as exc:
                    # Never retry a mutation whose response was lost: the world may have changed.
                    exc.add_note(json.dumps({"cycle": cycles, "elapsed_s": time.monotonic() - began,
                        "injections": dict(world.injections), "sensor_task_done": world.task.done(),
                        "history": len(target.history), "clouds": len(target.latest),
                        "clients": len(target.clients)}))
                    raise
                assert reply.status_code == 200 and reply.json()["ok"] is True
                assert reply.headers["access-control-allow-origin"] == CONSOLE
                marker, serial = world.marker, world.serial
                await receive_until(browser, lambda topic, data, marker=marker, kind=kind:
                    topic == "world/change" and marker in data["moved_blocks"] and data["kind"] == kind)
                gate = await receive_until(browser, lambda topic, data, serial=serial:
                    topic == "gate/request" and data["id"] == f"soak-gate-{serial}")
                answer = {"id": gate["id"], "approved": bool(cycles % 2), "by": "operator"}
                await browser.send(json.dumps({"topic": "gate/answer", "data": answer}))
                await receive_until(browser, lambda topic, data, answer=answer: topic == "gate/answer" and data == answer)
                command = {"text": f"soak control {serial}", "source": "typed"}
                await browser.send(json.dumps({"topic": "operator/command", "data": command}))
                await receive_until(browser, lambda topic, data, command=command: topic == "operator/command" and data == command)
                assert len(target.history) <= 200 and len(target.latest) <= 1 and len(target.clients) <= 2
                peaks["history"] = max(peaks["history"], len(target.history))
                peaks["clouds"] = max(peaks["clouds"], len(target.latest))
                peaks["clients"] = max(peaks["clients"], len(target.clients))
            cycles += 1
            elapsed = time.monotonic() - began
            if elapsed >= next_progress:
                print(json.dumps({"soak_elapsed_s": round(elapsed, 1), "connections": cycles,
                                  "observed_world_changes": observed["world/change"], "peaks": peaks}), flush=True)
                next_progress += 30
            await asyncio.sleep(min(0.25, max(0.0, duration - (time.monotonic() - began))))
    elapsed = time.monotonic() - began
    assert elapsed >= duration and cycles >= 2
    assert world.injections["aftershock"] and world.injections["block_added"]
    assert world.answers == cycles and world.commands == cycles
    assert peaks["history"] == 200 and peaks["clouds"] == 1 and peaks["cloud_points"] == 2048
    return {"requested_s": duration, "elapsed_s": round(elapsed, 3), "connections": cycles,
            "reconnects": cycles - 1, "injections": dict(world.injections), "gate_answers": world.answers,
            "operator_commands": world.commands, "observed_topics": dict(observed), "peaks": peaks}


def test_hub_soak_inject_reconnect_and_bounded_clouds(monkeypatch):
    duration = float(os.environ.get("HUB_SOAK_SECONDS", "2"))
    assert math.isfinite(duration) and 2 <= duration <= 600
    target, world = hub.Bus(), SyntheticWorld()
    monkeypatch.setattr(hub, "bus", target)
    monkeypatch.setattr(gem, "MODE", "off")
    monkeypatch.setattr(gem, "_calls", [])
    monkeypatch.setattr(gem, "_receipts", deque(maxlen=200))
    monkeypatch.setattr(gem, "_c", lambda: pytest.fail("soak attempted a model call"))
    original_import = hub.importlib.import_module

    async def start(bus):
        assert _sim_inject().install(world, bus)
        bus.subscribe("gate/answer", world.answer)
        bus.subscribe("operator/command", world.command)
        world.task = asyncio.create_task(world.pump(bus))
        return world

    def imports(name):
        return SimpleNamespace(start=start) if name == "soak_synthetic_lane" else original_import(name)

    monkeypatch.setattr(hub, "LANES", ("soak_synthetic_lane",))
    monkeypatch.setattr(hub.importlib, "import_module", imports)
    routes = list(hub.app.router.routes)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(hub.app, log_config=None, log_level="warning",
                                          access_log=False, lifespan="on"))
    worker = threading.Thread(target=lambda: asyncio.run(server.serve(sockets=[listener])), daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "soak server failed to start"
        result = asyncio.run(exercise(port, duration, target, world))
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
        hub.app.router.routes[:] = routes
    assert not worker.is_alive() and not target.clients and not target.subs
    assert world.task.cancelled() and gem.status()["calls_last_hour"] == 0
    result.update(backend="real localhost HTTP/WebSocket; synthetic world/sensors; actual sim/inject.py handler",
                  server_stopped=True, clients_after_shutdown=0, subscribers_after_shutdown=0,
                  runtime_sha256={path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in (Path(hub.__file__), Path(hub.__file__).with_name("points.py"), INJECT_PY)})
    output = Path("runs") / f"hub-soak-{duration:g}s.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result), flush=True)
