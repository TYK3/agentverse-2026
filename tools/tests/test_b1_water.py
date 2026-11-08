"""WATER-DELIVER-B1: the Responder carries water from L1 down to casualty c1 on B1 and sets it down there.

Nothing on the way down is scripted except one short leg on open L1 floor:
  1. sim.demo_descent.run(floor="B1"): the Scout maps L1 -> ground -> B1 with its own sensors and stops by c1;
  2. planner.levels.find_route over the Scout's final map, from where the Scout started on L1 to where it
     stopped by c1 (ramps R2 and R1): the Responder's route;
  3. a fresh LevelWorld with the Responder (levels.xml, LEVELS-RESPONDER) drives that route tick by tick;
     the Scout is parked out of the scene (its map is what is used). The Scout never mapped the Responder's
     corner of L1, so a straight leg on L1 takes the Responder from its start to the Scout's start first;
  4. place_supply water, then a second of physics.

Checked: the Responder arrives on B1, the water stays on board until it is placed, the water ends up resting
on B1's floor (not on L1 above c1: c1 is 0.46 m from the Responder's L1 corner in x, y alone) within reach
of c1, and every Responder tick is continuous (no step over its speed, height always on the floor).
About 40 s of MuJoCo.
"""

import math
from itertools import pairwise

import pytest

mujoco = pytest.importorskip("mujoco")

from planner.levels import find_route
from sim import responder as R
from sim.demo_descent import cell, run
from sim.levels import LEVEL_Z, LevelWorld

DT = 0.1
B1 = LEVEL_Z["B1"]
L1_LEG = [(0.2, 0.5), (0.5, 0.5)]     # from the Responder's start (x 0.2) south, then east to the Scout's start
NEAR_C1 = 0.5                          # metres: the water must rest this close to c1 (x, y) on B1
ON_FLOOR = 0.01                        # metres: the water's base is this close to B1's floor


@pytest.fixture(scope="module")
def delivery():
    descent = run(max_t=300.0, floor="B1")
    assert descent["reached"], descent["log"][-5:]
    w = LevelWorld(render=False)
    if mujoco.mj_name2id(w.m, mujoco.mjtObj.mjOBJ_BODY, "responder") < 0:
        pytest.fail("levels.xml has no Responder body (needs LEVELS-RESPONDER)")
    w.d.mocap_pos[w.scout_mocap] = [-50.0, -50.0, 10.0]    # the Scout is down on B1 by now: out of the way
    r = R.Responder(w.m, w.d, clock=lambda: w.t)
    start = r.pos.copy()
    fp = descent["final_pos"]
    planned = find_route(descent["map"], [], descent["start_cell"], cell(fp[0], fp[1], fp[2] - 0.075))
    assert planned["status"] == "ok", planned["status"]
    routes = {"r0": R.cells_along([tuple(start[:2])] + L1_LEG, k=descent["start_cell"][2]),
              "r1": planned["cells"]}
    trace, legs = [(w.t, *r.pos)], {}
    for rid, cells in routes.items():
        r.on_route({"id": rid, "robot": "responder", "cells": cells, "goal": "deliver water to c1",
                    "model": "local-astar"})
        r.on_action({"action": "move", "route": rid, "item": "water"})
        for _ in range(int(300 / DT)):
            r.step(DT)
            w.tick(DT)
            trace.append((w.t, *r.pos))
            if r.state != "moving":
                break
        legs[rid] = {"state": r.state, "pos": [round(float(v), 3) for v in r.pos],
                     "floor": round(r.floor_z, 3), "t": round(w.t, 1), "why": r.log[-1]["reason"]}
        if r.state != "arrived":
            break
    carrying_on_arrival = r.status()["carrying"]
    placed = r.on_action({"action": "place_supply", "route": "r1", "item": "water"})
    for _ in range(10):
        w.tick(DT)
    water = w.d.xpos[w.m.body("water").id].copy()
    geom = w.m.body_geomadr[w.m.body("water").id]
    return {"legs": legs, "responder": r, "trace": trace, "placed": placed, "water": water,
            "water_half": float(w.m.geom_size[geom][1]), "c1": w.m.body("casualty_c1").pos.copy(),
            "carrying_on_arrival": carrying_on_arrival}


def test_the_responder_drives_both_legs_down_to_b1(delivery):
    legs = delivery["legs"]
    assert [leg["state"] for leg in legs.values()] == ["arrived", "arrived"], legs
    assert abs(delivery["responder"].floor_z - B1) < 0.02, legs


def test_the_water_rides_along_until_it_is_placed(delivery):
    assert "water" in delivery["carrying_on_arrival"], delivery["legs"]
    assert delivery["placed"]["outcome"] == "done", delivery["placed"]
    assert "water" not in delivery["responder"].status()["carrying"]


def test_the_water_rests_on_b1_beside_c1(delivery):
    water, c1 = delivery["water"], delivery["c1"]
    base = water[2] - delivery["water_half"]
    assert abs(base - B1) < ON_FLOOR, f"water base at z {base:.3f}, B1 floor is {B1} (legs {delivery['legs']})"
    gap = math.dist(water[:2], c1[:2])
    assert gap < NEAR_C1, f"water {gap:.2f} m from c1 (x, y)"


def test_every_responder_tick_is_continuous(delivery):
    worst = max((math.dist(a[1:3], b[1:3]), a[0]) for a, b in pairwise(delivery["trace"]))
    assert worst[0] <= R.SPEED * DT + 1e-6, f"xy step {worst[0]:.4f} m at t={worst[1]:.1f}"
    rise = max((abs(b[3] - a[3]), a[0]) for a, b in pairwise(delivery["trace"]))
    assert rise[0] <= R.MAX_RISE * R.SPEED * DT + R.STEP_SLACK, f"height step {rise[0]:.4f} m at t={rise[1]:.1f}"
