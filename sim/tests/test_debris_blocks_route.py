"""DEBRIS-BLOCK-TEST: real injected rubble changes a sensed, physics-checked route.

Seam: World/inject -> MuJoCo/LiDAR -> Grid -> find_route -> World.verify.
This checks settled debris avoidance, not HTTP transport or moving-debris permits.
"""

import math

import pytest

from perception.grid import Grid
from planner.route import find_route
from sim import inject
from sim.world import World


def cell(x, y):
    return [math.floor(x / 0.05), math.floor(y / 0.05), 0]


def drive(world, target):
    world.goto({"target": target, "reason": "debris route test setup"})
    for _ in range(100):
        world.tick(0.1)
        if world.state != "moving":
            break
    assert world.state == "arrived", (target, world.state, world.pos)


def test_settled_debris_blocks_old_route_and_replan_avoids_it():
    world = World(render=False, seed=0)
    # Enter room 1 around its existing breach rubble, using real collision checks.
    for target in ([-0.5, 0.25, 0.075], [-1.0, 0.25, 0.075]):
        drive(world, target)

    grid = Grid()
    grid.add_sensors(world.sensors_message(camera=False))
    start, goal = cell(*world.pos[:2]), cell(-0.3, 0.25)
    original = find_route(grid.snapshot(world.t), [], start, goal)
    assert original["status"] == "ok"
    assert world.verify({"id": "before-debris", "cells": original["cells"]})["ok"] is True

    status, body = inject.handle(world, {"kind": "block_added", "pos": [-0.65, 0.25, 0.3]})
    assert (status, body) == (200, {"ok": True, "block": "x1"})
    events = []
    for _ in range(12):
        events.extend(world.tick(0.1))
    changes = [data for topic, data in events if topic == "world/change"]
    assert len(changes) == 1
    assert changes[0]["kind"] == "block_added"
    assert changes[0]["moved_blocks"] == ["x1"]
    assert world.d.xpos[world.m.body("x1").id][2] == pytest.approx(0.08, abs=0.01)

    # No truth cells or fabricated hazards enter the planner: only fresh real LiDAR.
    grid.begin_change(world.t)
    grid.add_sensors(world.sensors_message(camera=False))
    snapshot = grid.snapshot(world.t)
    occupied = {tuple(record["cell"]) for record in snapshot["cells"] if record["occupied"]}
    old_cells = {tuple(c) for c in original["cells"]}
    assert old_cells & occupied, "the new rubble must obstruct the formerly free route"

    replacement = find_route(snapshot, [], start, goal)
    assert replacement["status"] == "ok"
    assert replacement["cells"][0] == start
    assert replacement["cells"][-1] == goal
    assert replacement["cells"] != original["cells"]
    assert not {tuple(c) for c in replacement["cells"]} & occupied
    assert world.verify({"id": "after-debris", "cells": replacement["cells"]})["ok"] is True
    # verify checks future instability, not occupancy: a settled block can be stable.
    # The fresh sensed map, rather than a fake negative physics verdict, excludes it.

    # Reissuing the old straight traversal must hit the actual collision guard too.
    world.goto({"target": [-0.3, 0.25, 0.075], "reason": "retry original route"})
    for _ in range(100):
        world.tick(0.1)
        if world.state != "moving":
            break
    assert world.state == "blocked"
    assert world.pos[0] < -0.75  # stopped before the landed block's left face
