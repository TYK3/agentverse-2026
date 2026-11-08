"""RAY-BLOCK-REPRO: the Responder re-hits x1 on every re-plan and never finishes its move (#52 B1 runs).

On main e579ae3 + #52, B1 seeds 5 and 7 end 15/16 on "supply placed": after x1 lands in room 1 the
Responder stops beside it, at [-0.775, -1.125] (seed 5) or [-0.775, -1.175] (seed 7), facing north.
Every new route (about 39 of them) starts north along x = -0.775, only 0.05 m west of x1's west face,
and the collision ray on the Responder's right side (HALF_WIDTH 0.07 m) hits x1_rubble at x = -0.705
before the first step, so place_supply never runs.

This rebuilds that moment from the real scene: the real World, x1 dropped by the same inject call at
each run's spot, the real Responder, and a route from planner.route.find_route on the scene's true
occupancy (x1 included, as the ray-hit cell from #422 marks it). It is a strict xfail: it passes once
route.py keeps a drivable gap to x1, or the Responder can get clear of it, and then the mark must go.
"""

import math

import mujoco
import numpy as np
import pytest

from planner.route import find_route
from sim import inject
from sim import responder as R
from sim.world import World

RES = R.RES
GOAL = (-21, -15, 0)        # on the runs' own routes (r39 in seed 5), west of x1, toward c1
# (x1 centre where the run dropped it, Responder stop position) from runs/rescue-{5,7}.jsonl
SEEDS = {
    5: ((-0.625, -0.975), (-0.775, -1.125)),
    7: ((-0.625, -1.025), (-0.775, -1.175)),
}


def _true_map(world):
    """Seen cells over room 1's west half; occupied where a wall, rubble or supply box meets the
    collision ray's height band (the Responder and the Scout are left out)."""
    m, d = world.m, world.d
    skip = {m.body("responder").id}
    boxes = []
    for g in range(m.ngeom):
        if m.geom_type[g] != mujoco.mjtGeom.mjGEOM_BOX or int(m.geom_bodyid[g]) in skip:
            continue
        if "scout" in (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or ""):
            continue
        half = np.abs(d.geom_xmat[g].reshape(3, 3)) @ m.geom_size[g]
        c = d.geom_xpos[g]
        if c[2] - half[2] > 0.12 or c[2] + half[2] < 0.02:
            continue
        boxes.append((c[:2] - half[:2], c[:2] + half[:2]))
    cells = []
    for i in range(-28, -1):
        for j in range(-28, -9):
            x0, y0 = i * RES, j * RES
            occ = any(x0 < hi[0] and x0 + RES > lo[0] and y0 < hi[1] and y0 + RES > lo[1] for lo, hi in boxes)
            cells.append({"cell": [i, j, 0], "state": "seen", "occupied": bool(occ)})
    return {"res": RES, "cells": cells}


def _setup(seed):
    (bx, by), stop = SEEDS[seed]
    world = World(render=False)
    world._set_pose((-1.2, -1.7), 0.0)      # Scout parked out of the way, as test_ray_hit_cell.py
    assert inject.handle(world, {"kind": "block_added", "pos": [bx, by, 0.3]})[0] == 200
    for _ in range(20):                      # x1 falls and settles flat
        world.tick(0.1)
    r = R.Responder(world.m, world.d, clock=lambda: world.t)
    r._set_pose(stop, math.pi / 2)
    start = (math.floor(stop[0] / RES), math.floor(stop[1] / RES), 0)
    return world, r, find_route(_true_map(world), [], start, GOAL)


def _drive(world, r, cells, seconds=60):
    r.on_route({"id": "rb", "robot": "responder", "cells": cells, "goal": "test", "model": "local-astar"})
    r.on_action({"action": "move", "route": "rb", "item": "water"})
    for _ in range(int(seconds / 0.1)):
        r.step(0.1)
        world.tick(0.1)
        if r.state != "moving":
            break


@pytest.mark.parametrize("seed", sorted(SEEDS))
def test_scene_matches_the_runs(seed):
    """Not the bug, the setup: x1 lies where the run had it and a route to the goal exists."""
    world, _, route = _setup(seed)
    (bx, by), _ = SEEDS[seed]
    x1 = world.d.xpos[world.m.body("x1").id]
    assert abs(x1[0] - bx) < 0.01 and abs(x1[1] - by) < 0.01 and abs(x1[2] - 0.08) < 0.01
    assert route["status"] == "ok" and route["cells"][-1] == list(GOAL)


@pytest.mark.xfail(strict=True, reason="RAY-BLOCK-REPRO (#52): the route hugs x1 and the collision ray "
                                       "stops the Responder before its first step; fix in planner/route.py "
                                       "or sim/responder.py, then drop this mark")
@pytest.mark.parametrize("seed", sorted(SEEDS))
def test_responder_gets_past_x1(seed):
    world, r, route = _setup(seed)
    assert route["status"] == "ok"
    _drive(world, r, route["cells"])
    hit = r.last_hit[1] if r.last_hit else None
    assert r.state == "arrived", f"seed {seed}: {r.state} at {r.pos[:2].round(3).tolist()}, ray hit {hit}"
