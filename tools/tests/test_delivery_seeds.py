"""DELIVERY-SEEDS: the Responder delivers water to c1 end to end, seeds 0-4.

Same real lanes and checks as tools/tests/test_deliver.py (sim.start with loop=False and the planner
Loop on one in-process bus, GEMINI_MODE=off), repeated for seeds 0-4. Each seed sets Python's and
NumPy's RNGs and the sim's own RNG (acoustic noise), and moves the parked Scout and the delivery
goal by a seeded offset of up to one grid cell (0.05 m; never radially away from c1), so every seed
plans its own route. A seed
passes only if the gate refers, the operator's approval releases exactly move, place_supply,
release, the Responder is never refused or blocked, and the water ends on the floor within 0.6 m
of c1.
"""

import asyncio
import random

import pytest

pytest.importorskip("mujoco")

import numpy as np

import sim
from planner import loop as L
from planner.route import RoutePlanner
from planner.tests.test_loop import Bus, Clock, OffGem
from tools.tests.test_deliver import C1, GOAL, RES, START, cell, map_from_blocks

SEEDS = range(5)


def offsets(seed):
    """Deterministic per-seed offsets (dx, dy) in metres, each within one grid cell."""
    rng = random.Random(1000 + seed)
    return [(rng.uniform(-RES, RES), rng.uniform(-RES, RES)) for _ in range(2)]


def goal_for(seed):
    """GOAL moved by the seed's offset, minus any part pointing away from c1: the 0.6 m check is
    about c1, and the baseline already sits at about 0.55 m (see the PR), so a goal moved away
    from c1 would test the offset, not the delivery."""
    gx, gy = offsets(seed)[1]
    ux, uy = GOAL[0] - C1["pos"][0], GOAL[1] - C1["pos"][1]          # from c1 out to the goal
    norm = (ux * ux + uy * uy) ** 0.5
    away = (gx * ux + gy * uy) / norm
    if away > 0:
        gx, gy = gx - away * ux / norm, gy - away * uy / norm
    return (GOAL[0] + gx, GOAL[1] + gy)


def deliver(seed):
    (sx, sy) = offsets(seed)[0]
    goal = goal_for(seed)

    async def run():
        random.seed(seed)
        np.random.seed(seed)
        bus, clock = Bus(), Clock()
        world = await sim.start(bus, loop=False)
        world.rng = np.random.default_rng(seed)
        world._set_pose((-1.2 + sx, -1.7 + sy), 0.0)       # Scout parked out of the Responder's way
        router = RoutePlanner(bus)
        bus.subscribe("map/cells", router.update_map)
        lp = L.Loop(bus, router, gem=OffGem(), clock=clock, review_timeout=5.0).attach()
        await bus.publish("map/cells", map_from_blocks(bus.of("scene/loaded")[0]["blocks"]))
        await bus.publish("map/hazards", [])
        await bus.publish("map/casualties", [C1])
        await lp.mission(cell(*START), cell(*goal))
        (route,) = bus.of("route/proposed")
        (verified,) = bus.of("route/verified")
        outcome = bus.of("gate/decision")[-1]["outcome"]
        (req,) = bus.of("gate/request")
        before = list(bus.of("responder/action"))
        await bus.publish("gate/answer", {"id": req["id"], "approved": True, "by": "operator"})
        actions = [(a["action"], a["item"]) for a in bus.of("responder/action")]
        r = world.responder
        for _ in range(600):
            r.step(0.1)
            world.tick(0.1)
            await asyncio.sleep(0)
            if r.state != "moving" and not r.queue:
                break
        for _ in range(10):
            world.tick(0.1)
        water = world.d.xpos[world.m.body("water").id].copy()
        c1 = world.d.xpos[world.m.body("casualty_c1").id].copy()
        return {"route": route, "goal_cell": list(cell(*goal)), "verified": verified["ok"], "outcome": outcome,
                "before": before, "actions": actions, "log": r.log, "state": r.state,
                "carrying": r.status()["carrying"], "water": water, "c1": c1}

    return asyncio.run(run())


@pytest.mark.parametrize("seed", SEEDS)
def test_delivery_to_c1(seed):
    out = deliver(seed)
    assert out["route"]["cells"][-1] == out["goal_cell"] and out["verified"] is True
    assert out["outcome"] == "refer" and out["before"] == []
    assert out["actions"] == [("move", "water"), ("place_supply", "water"), ("release", "water")]
    outcomes = [e["outcome"] for e in out["log"]]
    assert "refused" not in outcomes and "blocked" not in outcomes, out["log"]
    assert out["state"] == "arrived" and "water" not in out["carrying"]
    dist = float(np.linalg.norm(out["water"][:2] - out["c1"][:2]))
    assert dist < 0.6, f"seed {seed}: water {dist:.2f} m from c1"
    assert out["water"][2] < 0.1, f"seed {seed}: water not on the floor"


def test_goal_never_moves_away_from_c1():
    def d(p):
        return ((p[0] - C1["pos"][0]) ** 2 + (p[1] - C1["pos"][1]) ** 2) ** 0.5
    # a sideways move of up to one cell can add at most RES**2 / (2 * 0.44 m) = 3 mm
    assert all(d(goal_for(s)) <= d(GOAL) + 0.003 for s in SEEDS)


def test_offsets_stay_within_one_cell_and_differ():
    all_offsets = [offsets(s) for s in SEEDS]
    assert all(abs(v) <= RES for o in all_offsets for xy in o for v in xy)
    assert len({tuple(map(tuple, o)) for o in all_offsets}) == len(SEEDS)
    assert offsets(3) == offsets(3)
