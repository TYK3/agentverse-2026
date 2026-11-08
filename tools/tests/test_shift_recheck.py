"""SHIFT-RECHECK-TEST: a slab shift injected through the hub's POST /inject stops both robots, and
neither moves on again until it has re-checked: the Scout re-scans the cells it had predicted at risk,
and the planner holds the Responder until a fresh map comes in and the new route is physics-checked.

Deterministic: the sim world is ticked by hand in sim time (no sim loop, no sleeps) and the hub app
is driven with TestClient without its lifespan, so no lanes start in the background.
"""

import asyncio

import pytest

pytest.importorskip("mujoco")
TestClient = pytest.importorskip("fastapi.testclient").TestClient

import numpy as np

from coord import hub
from perception.explore import Explorer
from perception.grid import Grid
from planner import loop as L
from planner.route import RoutePlanner
from planner.tests.test_loop import START, Bus, Clock, OffGem, two_gap_map
from sim import demo_responder, inject
from sim import responder as R
from sim.world import World

K, Z = 1, 0.075
AT_RISK = [{"cell": [30, 0, 0], "status": "at_risk"}, {"cell": [31, 0, 0], "status": "at_risk"}]


def corridor_explorer():
    """A seen 2 m corridor along +x, unknown at the far end, with the Scout at its near end."""
    g = Grid()
    for i in range(40):
        for j in range(-7, 8):
            g.free((i, j, K))
    for i in range(-1, 40):
        g.hit((i, -8, K))
        g.hit((i, 8, K))
    for j in range(-8, 9):
        g.hit((-1, j, K))
    e = Explorer(g)
    e.on_sensors({"pose": {"pos": [0.1, 0.025, Z]}})
    return e


@pytest.fixture
def hub_inject():
    """Wire the sim's POST /inject onto the hub app for one World; put the hub's routes back after."""
    saved = list(hub.app.router.routes)
    world = World(render=False)
    world._set_pose((-1.2, -1.7), 0.0)              # Scout body parked out of the Responder's way
    assert inject.install(world, hub.bus) is True
    try:
        yield world, TestClient(hub.app)
    finally:
        hub.app.router.routes[:] = saved


def test_slab_shift_via_inject_stops_both_robots_until_they_recheck(hub_inject):
    world, client = hub_inject
    bus, clock = Bus(), Clock()

    # Responder (sim) mid-move on route r1, with a supply drop queued behind the move.
    resp = R.Responder(world.m, world.d, clock=lambda: world.t, shaking=lambda: world.shaking)
    resp.on_route({"id": "r1", "robot": "responder", "cells": R.cells_along(demo_responder.ROUTES["r1"]),
                   "goal": "deliver water to c1", "model": "local-astar"})
    resp.on_action({"action": "move", "route": "r1", "item": "water"})
    resp.on_action({"action": "place_supply", "route": "r1", "item": "water"})
    for _ in range(10):
        resp.step(0.1)
        world.tick(0.1)
    assert resp.state == "moving" and resp.queue

    # Planner loop executing a verified route; Scout exploring a frontier with two at-risk cells.
    router = RoutePlanner(bus)
    bus.subscribe("map/cells", router.update_map)
    lp = L.Loop(bus, router, gem=OffGem(), clock=clock, review_timeout=5.0).attach()
    explorer = corridor_explorer()
    explorer.on_hazards(AT_RISK)
    assert explorer.tick(0.0)["reason"].startswith("frontier")
    bus.subscribe("world/change", resp.on_world_change)
    bus.subscribe("world/change", explorer.on_change)

    async def go():
        await bus.publish("map/cells", two_gap_map())
        await bus.publish("map/hazards", [])
        await bus.publish("map/casualties", [{"id": "c1", "pos": [0.85, 0.35, 0], "confidence": 0.9,
                                              "clues": ["thermal", "sound"],
                                              "vitals": {"breathing_rate": 14, "simulated": True}}])
        await lp.mission(START, (8, 3, 0))
        await bus.publish("route/verified", {"id": "r1", "ok": True, "unstable_cells": [], "detail": ""})
    asyncio.run(go())
    assert lp.state == L.EXECUTING

    # The unscripted change, through the hub's HTTP endpoint the console uses.
    r = client.post("/inject", json={"kind": "aftershock"})
    assert (r.status_code, r.json()) == (200, {"ok": True})
    assert world.shaking

    # The Responder stops on the first tick of the shake and stays put through it.
    resp.step(0.1)
    assert resp.state == "frozen" and not resp.queue and resp.log[-1]["outcome"] == "frozen"
    here = resp.pos.copy()
    changes = []
    for _ in range(35):
        resp.step(0.1)
        changes += [d for t, d in world.tick(0.1) if t == "world/change"]
    assert np.allclose(resp.pos, here)
    assert len(changes) == 1 and changes[0]["kind"] == "aftershock"
    assert "b10" in changes[0]["moved_blocks"]          # the leaning slab shifted

    actions_before = len(bus.of("responder/action"))
    proposed_before = len(bus.of("route/proposed"))
    clock.now = 30.0
    asyncio.run(bus.publish("world/change", changes[0]))

    # Planner: route dropped, Responder held, waiting for a re-scan, nothing new sent to the Responder.
    log = bus.of("log/decision")[-1]
    assert log["outcome"] == "replanning" and "waiting for the Scout to re-scan" in log["reason"]
    assert "Responder held" in log["reason"]
    assert lp.state == L.IDLE and lp.route is None and lp.waiting_scan
    assert len(bus.of("responder/action")) == actions_before
    assert len(bus.of("route/proposed")) == proposed_before

    # Scout: frontier dropped, the next scout/goto is a re-scan of the predicted at-risk cell.
    assert explorer.target is None
    assert explorer.tick(31.0)["reason"] == "re-scan after the aftershock: predicted at-risk cell [30, 0, 0]"

    # Responder still parked while nothing has been re-checked.
    for _ in range(10):
        resp.step(0.1)
        world.tick(0.1)
    assert np.allclose(resp.pos, here) and resp.state == "frozen"

    # Only a fresh map lets the planner move again, and then with a new route that goes back
    # through the physics check (route/proposed, not a direct responder/action).
    clock.now = 32.0
    asyncio.run(bus.publish("map/cells", {"t": 32, "res": 0.1, "cells": [
        {"cell": [4, 1, 0], "state": "unknown", "occupied": False}]}))
    new = bus.of("route/proposed")[proposed_before:]
    assert len(new) == 1 and new[0]["id"] != "r1"
    assert "map re-scanned after aftershock moved" in bus.of("log/decision")[-1]["perception"]
    assert len(bus.of("responder/action")) == actions_before
    assert lp.state == L.PROPOSED
