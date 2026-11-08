"""RAY-HIT-CELL: when the collision ray stops the Responder, it publishes where the ray hit.

Real World (backup scene) and the real Responder; no log events are made up. The planner needs the
hit cell (planner/route.py), since the "blocked" record only gives the Responder's own position.
"""

import math
import re

import numpy as np
import pytest

from sim import responder as R
from sim.world import World

HIT = re.compile(r"^robot responder route (\S+) hit (\S+) at \[(-?\d+\.\d+), (-?\d+\.\d+)\] "
                 r"cell \[(-?\d+), (-?\d+), (-?\d+)\]$")


def _run(points, seconds=120):
    world = World(render=False)
    world._set_pose((-1.2, -1.7), 0.0)      # Scout parked out of the way
    sent = []
    r = R.Responder(world.m, world.d, publish=lambda topic, data: sent.append((topic, data)),
                    clock=lambda: world.t)
    r.on_route({"id": "rw", "robot": "responder", "cells": R.cells_along(points), "goal": "test",
                "model": "local-astar"})
    r.on_action({"action": "move", "route": "rw", "item": "water"})
    for _ in range(int(seconds / 0.1)):
        r.step(0.1)
        world.tick(0.1)
        if r.state != "moving":
            break
    return world, r, [d for t, d in sent if t == "log/decision"]


def test_blocked_move_publishes_the_ray_hit_cell_first():
    # Into room 1, then east at interior wall b6 (x = 0, face at x = -0.05), as test_responder.py.
    world, r, logs = _run([(-0.48, -1.77), (-0.48, -0.6), (0.6, -0.6)])
    assert r.state == "blocked"
    hits = [d for d in logs if d["outcome"] == "ray_hit"]
    assert len(hits) == 1, logs
    hit = hits[0]
    # It comes just before the unchanged "blocked" record, so a planner has the cell when it re-plans.
    blocked = logs[logs.index(hit) + 1]
    assert blocked["outcome"] == "blocked"
    assert blocked["reason"] == "collision ray: block ahead on route rw, stopped"
    assert blocked["perception"].startswith("responder at [")
    assert logs[-1] is blocked and r.log[-1] is blocked and hit in r.log
    assert hit["model"] == "sim" and hit["physics"] == "mujoco" and hit["t"] == blocked["t"]

    m = HIT.match(hit["reason"])
    assert m, hit["reason"]
    route, geom, x, y = m[1], m[2], float(m[3]), float(m[4])
    cell = [int(m[5]), int(m[6]), int(m[7])]
    assert route == "rw" and geom == "b6_wall"
    assert hit["perception"] == f"responder ray hit at [{m[3]}, {m[4]}], cell [{m[5]}, {m[6]}, {m[7]}]"
    # The hit is on b6's west face, ahead of the stopped Responder, inside its ray reach.
    g = world.m.geom("b6_wall")
    lo = world.d.geom_xpos[g.id][:2] - world.m.geom_size[g.id][:2]
    hi = world.d.geom_xpos[g.id][:2] + world.m.geom_size[g.id][:2]
    assert abs(x - lo[0]) < 0.002 and lo[1] - 0.002 <= y <= hi[1] + 0.002
    reach = np.linalg.norm(np.array([x, y]) - r.pos[:2])
    assert reach < math.hypot(R.HALF_LEN + R.GAP + R.SPEED * 0.1, R.HALF_WIDTH) + 0.002
    # Same cell rule as perception's map and the route cells: floor(pos / RES), k from the route.
    assert cell == [math.floor(x / R.RES), math.floor(y / R.RES), 0]


def test_ray_hit_record_matches_the_contract():
    messages = pytest.importorskip("coord.messages")
    _, _, logs = _run([(-0.48, -1.77), (-0.48, -0.6), (0.6, -0.6)])
    hit = next(d for d in logs if d["outcome"] == "ray_hit")
    assert messages.validate_payload("log/decision", hit) == hit


def test_no_ray_hit_on_a_clear_route():
    _, r, logs = _run([(-0.48, -1.77), (-0.48, -1.2)])
    assert r.state == "arrived"
    assert not [d for d in logs if d["outcome"] == "ray_hit"]

