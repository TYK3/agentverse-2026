"""E2E-LOG-CHECK: an end-to-end run's decision log is complete and traceable.

Real lanes on one in-process bus, ticked by hand in sim time (no sim loop, no sleeps): the sim
(sim.start, loop=False: world, physics check, Responder) and the planner loop. The planner's map
comes from the scene/loaded blocks, as in test_deliver.py. The run: mission to c1, gate referred
and approved, Responder sets off, POST /inject aftershock, re-plan, approved again, water delivered.
Then every log/decision is checked against coord/CONTRACT.md and for traceability.
"""

import asyncio
import json
import math
import re

import pytest

pytest.importorskip("mujoco")
TestClient = pytest.importorskip("fastapi.testclient").TestClient

import sim
from coord import hub
from planner import loop as L
from planner.route import RoutePlanner
from planner.tests.test_loop import Bus, Clock, OffGem
from sim import inject

RES, PAD = 0.05, 0.0  # physical occupancy; planner applies the chassis clearance
START, GOAL = (-0.5, -1.77), (1.77, 0.62)
C1 = {"id": "c1", "pos": [2.0, 1.0, 0.0], "confidence": 0.4, "clues": ["thermal"],
      "vitals": {"breathing_rate": 14, "simulated": True}}
FIELDS = {"t", "perception", "model", "physics", "outcome", "reason"}
# Image data, prompts, keys or tokens must never reach the log the console shows and records.
LEAKS = re.compile(r"data:image|base64|;base64,|[A-Za-z0-9+/]{120,}|prompt|reply with json|api[_-]?key|"
                   r"secret|token|password|bearer|AIza[0-9A-Za-z_-]{10,}|sk-[A-Za-z0-9]{16,}", re.IGNORECASE)


def cell(x, y):
    return (math.floor(x / RES), math.floor(y / RES), 0)


def map_from_blocks(blocks):
    cells = []
    for i in range(int(-1.5 / RES), int(2.5 / RES)):
        for j in range(int(-2.0 / RES), int(1.5 / RES)):
            x, y = (i + 0.5) * RES, (j + 0.5) * RES
            occ = any(abs(x - b["pos"][0]) <= b["size"][0] + PAD and abs(y - b["pos"][1]) <= b["size"][1] + PAD
                      and b["pos"][2] - b["size"][2] < 0.2 for b in blocks)
            cells.append({"cell": [i, j, 0], "state": "seen", "occupied": occ})
    return {"t": 0, "res": RES, "cells": cells}


@pytest.fixture(scope="module")
def run():
    """One full run; returns the bus (every message in order) and the final Responder status."""
    saved = list(hub.app.router.routes)

    async def go():
        bus, clock = Bus(), Clock()
        world = await sim.start(bus, loop=False)
        world._set_pose((-1.2, -1.7), 0.0)              # Scout parked out of the Responder's way
        assert inject.install(world, hub.bus) is True
        client = TestClient(hub.app)
        router = RoutePlanner(bus)
        bus.subscribe("map/cells", router.update_map)
        lp = L.Loop(bus, router, gem=OffGem(), clock=clock, review_timeout=5.0).attach()
        world_map = map_from_blocks(bus.of("scene/loaded")[0]["blocks"])

        async def tick(n, until_stopped=False):
            r = world.responder
            for _ in range(n):
                r.step(0.1)
                for topic, data in world.tick(0.1):      # what sim.run publishes each tick
                    await bus.publish(topic, data)
                clock.now = world.t                      # planner and sim share one clock
                await asyncio.sleep(0)                   # let the Responder's log/decision tasks run
                if until_stopped and r.state != "moving" and not r.queue:
                    return

        async def approve():
            req = bus.of("gate/request")[-1]
            await bus.publish("gate/answer", {"id": req["id"], "approved": True, "by": "operator"})

        await bus.publish("map/cells", world_map)
        await bus.publish("map/hazards", [])
        await bus.publish("map/casualties", [C1])
        await lp.mission(cell(*START), cell(*GOAL))
        await approve()
        await tick(10)
        assert client.post("/inject", json={"kind": "aftershock"}).status_code == 200
        await tick(35)                                   # the 3 s shake, then world/change
        await tick(11)
        await bus.publish("map/cells", world_map)        # the Scout's re-scan
        await approve()
        await tick(600, until_stopped=True)
        await tick(5)
        return bus, world.responder.status()

    try:
        return asyncio.run(go())
    finally:
        hub.app.router.routes[:] = saved


def logs(bus):
    return bus.of("log/decision")


def test_every_entry_has_the_contract_fields(run):
    bus, _ = run
    entries = logs(bus)
    assert len(entries) >= 15
    for e in entries:
        assert set(e) == FIELDS, e
        assert isinstance(e["t"], (int, float)) and e["t"] >= 0
        assert all(isinstance(e[k], str) for k in FIELDS - {"t"})
        assert e["outcome"] and e["reason"] and e["model"], e


def test_t_never_goes_backwards(run):
    ts = [e["t"] for e in logs(run[0])]
    assert ts == sorted(ts), ts


def test_every_move_follows_a_verified_route_and_an_approved_gate(run):
    bus, status = run
    sent = bus.sent
    moves = [i for i, (t, d) in enumerate(sent) if t == "responder/action" and d["action"] == "move"]
    assert len(moves) == 2                               # one before the aftershock, one after
    for i in moves:
        rid = sent[i][1]["route"]
        before = sent[:i]
        assert any(t == "route/verified" and d["id"] == rid and d["ok"] for t, d in before), rid
        reqs = [d["id"] for t, d in before if t == "gate/request" and d["route"] == rid]
        assert reqs and any(t == "gate/answer" and d["id"] in reqs and d["approved"] is True
                            and d["by"] == "operator" for t, d in before), rid
        # ... and the same trace is readable from the log alone.
        log = [d for t, d in before if t == "log/decision"]
        assert any(f"{rid} verified" in e["physics"] for e in log), rid
        assert any(e["outcome"] == "act" and e["reason"] == f"human approved {rid}" for e in log), rid
        act = next(d for t, d in sent[i:] if t == "log/decision" and d["model"] == "sim")
        assert act["outcome"] == "act" and act["perception"].endswith(f"move {rid}"), act
    assert status["state"] == "arrived" and "water" not in status["carrying"]


def test_aftershock_gives_replanning_then_a_new_route_with_a_reason(run):
    entries = logs(run[0])
    frozen = [k for k, e in enumerate(entries) if e["outcome"] == "frozen"]
    replan = [k for k, e in enumerate(entries) if e["outcome"] == "replanning"]
    assert frozen and replan and frozen[0] < replan[0]
    e = entries[replan[0]]
    assert e["perception"].startswith("aftershock moved") and "Responder held" in e["reason"]
    after = [x for x in entries[replan[0] + 1:] if x["outcome"] == "proposed"]
    assert after, "no new route after the aftershock"
    assert after[0]["perception"].startswith("map re-scanned after aftershock moved")
    assert re.match(r"route r\d+: \d+ seen cells to deliver water to c1", after[0]["reason"]), after[0]
    old = [x for x in entries[:replan[0]] if x["outcome"] == "proposed"]
    assert after[0]["reason"].split(":")[0] != old[-1]["reason"].split(":")[0]   # a new route id


def test_no_image_data_prompts_or_secrets(run):
    for e in logs(run[0]):
        text = json.dumps(e)
        assert not LEAKS.search(text), e
        assert len(text) < 1000, e
