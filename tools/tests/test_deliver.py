"""DELIVER-TEST: the Responder delivers water to casualty c1 end to end on the backup scene.

Real lanes on one in-process bus: the sim (sim.start, loop=False: the MuJoCo world, its physics check
and the Responder) and the planner loop (router, physics verify, gate, dispatch). The planner's map
is built from the blocks in scene/loaded instead of the Scout's LiDAR, so the run is the same every
time. Casualty confidence 0.4 puts the gate in the refer band: the operator approves gate/request,
then the planner sends move, place_supply, release and the sim carries them out. The world is ticked
by hand in sim time (no sim loop, no sleeps).
"""

import asyncio
import math

import pytest

pytest.importorskip("mujoco")

import numpy as np

import sim
from planner import loop as L
from planner.route import RoutePlanner
from planner.tests.test_loop import Bus, Clock, OffGem

RES = 0.05
PAD = 0.08                         # metres added round every block for the Responder's chassis
START = (-0.5, -1.77)              # the Responder's start pose on the backup scene
GOAL = (1.77, 0.62)                # beside casualty c1 in room 3 (the end of sim.demo_responder's r2)
C1 = {"id": "c1", "pos": [2.0, 1.0, 0.0], "confidence": 0.4, "clues": ["thermal"],
      "vitals": {"breathing_rate": 14, "simulated": True}}


def cell(x, y):
    return (math.floor(x / RES), math.floor(y / RES), 0)


def map_from_blocks(blocks):
    """map/cells over the backup scene: every cell seen; occupied where a low block (+PAD) covers it."""
    cells = []
    for i in range(int(-1.5 / RES), int(2.5 / RES)):
        for j in range(int(-2.0 / RES), int(1.5 / RES)):
            x, y = (i + 0.5) * RES, (j + 0.5) * RES
            occ = any(abs(x - b["pos"][0]) <= b["size"][0] + PAD and abs(y - b["pos"][1]) <= b["size"][1] + PAD
                      and b["pos"][2] - b["size"][2] < 0.2 for b in blocks)
            cells.append({"cell": [i, j, 0], "state": "seen", "occupied": occ})
    return {"t": 0, "res": RES, "cells": cells}


def test_responder_delivers_water_to_c1_end_to_end():
    async def run():
        bus, clock = Bus(), Clock()
        world = await sim.start(bus, loop=False)
        world._set_pose((-1.2, -1.7), 0.0)          # Scout parked out of the Responder's way
        router = RoutePlanner(bus)
        bus.subscribe("map/cells", router.update_map)
        lp = L.Loop(bus, router, gem=OffGem(), clock=clock, review_timeout=5.0).attach()

        await bus.publish("map/cells", map_from_blocks(bus.of("scene/loaded")[0]["blocks"]))
        await bus.publish("map/hazards", [])
        await bus.publish("map/casualties", [C1])
        await lp.mission(cell(*START), cell(*GOAL))

        # Route proposed and physics verified by the sim, then referred to the operator.
        (route,) = bus.of("route/proposed")
        assert route["robot"] == "responder" and route["cells"][-1] == list(cell(*GOAL))
        (verified,) = bus.of("route/verified")
        assert verified["id"] == route["id"] and verified["ok"] is True
        assert bus.of("gate/decision")[-1]["outcome"] == "refer"
        (req,) = bus.of("gate/request")
        assert req["route"] == route["id"] and lp.state == L.GATED
        assert bus.of("responder/action") == []      # nothing moves before the operator answers

        await bus.publish("gate/answer", {"id": req["id"], "approved": True, "by": "operator"})
        assert [(a["action"], a["route"], a["item"]) for a in bus.of("responder/action")] == [
            ("move", route["id"], "water"), ("place_supply", route["id"], "water"),
            ("release", route["id"], "water")]

        r = world.responder
        for _ in range(600):                         # at most 60 s of sim time
            r.step(0.1)
            world.tick(0.1)
            await asyncio.sleep(0)                   # let the Responder's log/decision publishes run
            if r.state != "moving" and not r.queue:
                break
        for _ in range(10):                          # one second for the water to settle
            world.tick(0.1)
        return world, r, route["id"]

    world, r, rid = asyncio.run(run())
    outcomes = [e["outcome"] for e in r.log]
    assert "refused" not in outcomes and "blocked" not in outcomes, r.log
    assert r.state == "arrived"
    done = [(e["perception"].split("], ")[-1], e["reason"]) for e in r.log if e["outcome"] == "done"]
    assert [p for p, _ in done] == [f"move {rid}", "place_supply water", "release water"], r.log
    assert done[0][1] == f"arrived at the end of route {rid}" and done[1][1].startswith("placed water at ")
    assert "water" not in r.status()["carrying"]
    water = world.d.xpos[world.m.body("water").id]
    c1 = world.d.xpos[world.m.body("casualty_c1").id]
    assert np.linalg.norm(water[:2] - c1[:2]) < 0.6, "water should be set down beside c1"
    assert water[2] < 0.1, "water should be on the floor"
