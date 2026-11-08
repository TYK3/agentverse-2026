"""B2-DELIVERY: a real run delivers water to casualty c2 on B2.

The Scout finds its own way from L1 down to the goal beside c2 (tools/play.descend, the real closed
loop of sim.demo_descent: LevelWorld physics, perception.levels, planner.levels). The Responder then
plans its own route over the map the Scout built (planner.levels.find_route) from where it stands on
L1 to a free cell short of the parked Scout, drives it with sim.responder.Responder (collision rays,
floor following down ramps R2, R1 and R3) and sets the water down. Checks:
  - the Scout reached the B2 goal and the Responder's route spans L1 down to B2,
  - the Responder arrives (never blocked) and ends on the B2 floor, having moved without a jump,
  - the water is released, lies on the B2 floor, and is within REACH_C2 of c2.
Nothing about the route is scripted. Skips without MuJoCo.
"""

import itertools
import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

B2_Z = -1.2
REACH_C2 = 0.8        # metres: water set down this close to c2 (goal is 0.5 m from it, plus set-down)
SCOUT_CLEAR = 0.45    # metres: the Responder's route ends this far from the parked Scout
MAX_STEP = 0.05       # metres per 0.1 s tick: 0.2 m/s plus a ramp's rise, with margin
K_B2 = round(B2_Z / 0.05)


def short_of(cells, point, clear, res=0.05):
    """`cells` cut at the last cell whose centre is at least `clear` metres from point (x, y)."""
    keep = [c for c in cells if math.dist(((c[0] + 0.5) * res, (c[1] + 0.5) * res), point) >= clear]
    if not keep:
        return []
    last = max(i for i, c in enumerate(cells) if c in keep)
    return cells[:last + 1]


def test_short_of_cuts_the_route_before_the_point():
    cells = [[i, 0, 0] for i in range(10)]
    assert short_of(cells, (0.475, 0.025), 0.09) == cells[:8]
    assert short_of(cells, (0.0, 0.0), 10.0) == []


@pytest.fixture(scope="module")
def delivery():
    pytest.importorskip("mujoco")
    import numpy as np
    import play

    from planner.levels import find_route
    from sim import responder as R
    from sim.demo_descent import cell
    from sim.levels import LevelWorld

    w = LevelWorld(render=False)
    scout = play.descend(w, floor="B2", max_t=500.0)
    m, d = w.m, w.d
    r = R.Responder(m, d, clock=lambda: w.t, shaking=lambda: w.shaking)
    start = r.pos.copy()
    plan = find_route(scout["map"], [], cell(start[0], start[1], r.floor_z), scout["goal_cell"])
    route = short_of(plan.get("cells") or [], w.pos[:2], SCOUT_CLEAR)
    r.on_route({"id": "b2", "robot": "responder", "cells": route, "goal": "deliver water to c2"})
    r.on_action({"action": "move", "route": "b2", "item": "water"})
    trace = [r.pos.copy()]
    while r.state == "moving" and w.t < 900.0:
        play._tick(w, None, False, extra=lambda: r.step(play.DT))
        trace.append(r.pos.copy())
    placed = r.on_action({"action": "place_supply", "route": "b2", "item": "water"}) if r.state == "arrived" else None
    for _ in range(50):          # let the water settle
        play._tick(w, None, False)
    water = d.xpos[m.body("water").id].copy()
    c2 = d.xpos[m.body("casualty_c2").id].copy()
    steps = [float(np.linalg.norm(b - a)) for a, b in itertools.pairwise(trace)]
    return {"scout": scout, "plan": plan, "route": route, "r": r, "placed": placed, "water": water,
            "c2": c2, "max_step": max(steps) if steps else 0.0, "log": r.log}


def test_scout_reached_b2_and_the_route_spans_l1_to_b2(delivery):
    assert delivery["scout"]["reached"], delivery["scout"]["log"][-3:]
    assert delivery["plan"]["status"] == "ok", delivery["plan"].get("reason")
    ks = [c[2] for c in delivery["route"]]
    assert ks and ks[0] >= 10 and abs(ks[-1] - K_B2) <= 3, (ks[:1], ks[-1:])


def test_responder_arrives_on_b2_without_a_jump(delivery):
    r = delivery["r"]
    assert r.state == "arrived", [e["reason"] for e in delivery["log"]][-3:]
    assert abs(r.floor_z - B2_Z) < 0.05, r.floor_z
    assert delivery["max_step"] <= MAX_STEP, delivery["max_step"]


def test_water_is_set_down_on_b2_beside_c2(delivery):
    assert delivery["placed"] and delivery["placed"]["outcome"] == "done", delivery["placed"]
    assert not delivery["r"].holding("water")
    water, c2 = delivery["water"], delivery["c2"]
    assert abs(water[2] - (B2_Z + 0.06)) < 0.05, f"water at z {water[2]:.3f}, not on the B2 floor"
    dist = math.dist(water[:2], c2[:2])
    assert dist < REACH_C2, f"water {dist:.2f} m from c2"
