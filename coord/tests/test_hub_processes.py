"""HUB-PROCESSES: with HUB_PROCESSES=1 the hub runs the sim lane in its own process behind the same bus.

This module is also a tiny lane (start(bus) below) that the hub can run in a process: it ticks at 10 Hz
like the sim and answers scout/goto, so the bridge is tested without MuJoCo. The last test runs the real
sim lane in a process (skipped without MuJoCo).
"""

import asyncio
import multiprocessing
import os
import time

import pytest
from fastapi.testclient import TestClient

from coord import hub

LANE = __name__          # this module, importable by the spawned process as a lane
TICK_S = 0.1


async def start(bus):
    """A stand-in lane: publishes 'started' with its pid, ticks at 10 Hz and answers scout/goto."""
    pid = os.getpid()

    def decision(outcome, reason):
        return {"t": round(time.time() % 100000, 3), "perception": str(pid), "model": "lane-test",
                "physics": "", "outcome": outcome, "reason": reason}

    async def on_goto(data):
        await bus.publish("log/decision", decision("goto", data["reason"]))

    bus.subscribe("scout/goto", on_goto)
    await bus.publish("log/decision", decision("started", "lane up"))

    async def tick():
        n = 0
        while True:
            n += 1
            await bus.publish("log/decision", decision("tick", str(n)))
            await asyncio.sleep(TICK_S)

    class World:
        task = asyncio.create_task(tick())

    return World()


def test_flag_is_off_by_default():
    assert not hub.processes_enabled({})
    assert not hub.processes_enabled({"HUB_PROCESSES": "0"})
    assert hub.processes_enabled({"HUB_PROCESSES": "1"})


def test_lane_process_bridges_publish_and_subscribe():
    async def scenario():
        bus = hub.Bus()
        seen = []
        bus.subscribe("log/decision", seen.append)
        lane = hub.LaneProcess(LANE, bus)
        assert await lane.start(ready_s=60)
        try:
            started = [d for d in seen if d["outcome"] == "started"]
            assert started and int(started[0]["perception"]) != os.getpid()   # it ran in another process
            await bus.publish("scout/goto", {"target": [0.5, 0.5, 0.0], "reason": "look here"})
            for _ in range(50):
                if any(d["outcome"] == "goto" for d in seen):
                    break
                await asyncio.sleep(0.1)
            assert [d["reason"] for d in seen if d["outcome"] == "goto"] == ["look here"]
            assert any(d["outcome"] == "tick" for d in seen)
        finally:
            await lane.stop()
        assert not lane.process.is_alive()

    asyncio.run(scenario())


def test_a_blocked_hub_loop_does_not_stop_the_lane_ticking():
    """The point of HUB-PROCESSES: while a slow callback holds the hub's loop for 1 s, the lane process
    keeps its 10 Hz tick; the ticks it made meanwhile arrive once the hub is free again."""
    async def scenario():
        bus = hub.Bus()
        ticks = []
        bus.subscribe("log/decision", lambda d: ticks.append(d) if d["outcome"] == "tick" else None)
        lane = hub.LaneProcess(LANE, bus)
        assert await lane.start(ready_s=60)
        try:
            await asyncio.sleep(0.5)
            before = time.time() % 100000
            time.sleep(1.0)  # noqa: ASYNC251 - deliberately blocks the hub loop, as a slow planner step would
            after = time.time() % 100000
            await asyncio.sleep(0.5)
            during = [d for d in ticks if before <= d["t"] <= after]
            assert len(during) >= 6, f"only {len(during)} ticks while the hub loop was blocked"
        finally:
            await lane.stop()

    asyncio.run(scenario())


@pytest.fixture
def hub_with(monkeypatch):
    def setup(lanes, flag):
        monkeypatch.setattr(hub, "bus", hub.Bus())
        monkeypatch.setattr(hub, "LANES", lanes)
        monkeypatch.setattr(hub, "PROCESS_LANES", lanes)
        if flag:
            monkeypatch.setenv("HUB_PROCESSES", "1")
        else:
            monkeypatch.delenv("HUB_PROCESSES", raising=False)
        original = hub.importlib.import_module

        def imports(name):
            if name == "coord.gem":
                raise ModuleNotFoundError(name=name)
            return original(name)

        monkeypatch.setattr(hub.importlib, "import_module", imports)
    routes = list(hub.app.router.routes)
    yield setup
    hub.app.router.routes[:] = routes


def first_started(websocket):
    for _ in range(200):
        msg = websocket.receive_json()
        if msg["topic"] == "log/decision" and msg["data"]["outcome"] == "started":
            return int(msg["data"]["perception"])
    raise AssertionError("no 'started' from the lane")


@pytest.mark.parametrize("flag", [False, True])
def test_hub_runs_the_lane_in_process_only_with_the_flag(hub_with, flag):
    hub_with((LANE,), flag)
    with TestClient(hub.app) as client, client.websocket_connect("/ws") as websocket:
        pid = first_started(websocket)
        assert (pid != os.getpid()) is flag
        websocket.send_json({"topic": "status/link", "data": {"online": True}})
    # Hub shutdown stops the lane process too.
    assert not [p for p in multiprocessing.active_children() if p.name.startswith("lane-")]


def test_real_sim_lane_in_a_process_serves_the_bus_and_inject(hub_with):
    pytest.importorskip("mujoco")
    hub_with(("sim",), True)
    os.environ.pop("SIM_SCENE", None)
    with TestClient(hub.app) as client, client.websocket_connect("/ws") as websocket:
        topics = set()
        for _ in range(400):
            topics.add(websocket.receive_json()["topic"])
            if {"scene/loaded", "responder/pose"} <= topics:
                break
        assert {"scene/loaded", "responder/pose"} <= topics
        reply = client.post("/inject", json={"kind": "aftershock"})
        assert reply.status_code == 200, reply.text
        assert reply.json() == {"ok": True}
        end = time.monotonic() + 30
        while time.monotonic() < end:
            msg = websocket.receive_json()
            if msg["topic"] == "world/change":
                assert msg["data"]["kind"] == "aftershock"
                break
        else:
            raise AssertionError("no world/change after the injected aftershock")
