"""B4-WALL-STOP: a replan that starts in the cell the Responder is parked in does not turn it into b4.

B1 seed 5 (board SUPPLY-DIAG, cause 2): the Responder is parked at (-0.49, -1.24) and every replan's
route starts at that cell's centre (-0.475, -1.225), then runs north past b4_wall's west end
(x -0.40, south face y -1.05). Turning to face the centre swung the right collision ray into b4 at
(-0.399, -1.05), and every replan stopped there (39 blocks). It now drives parallel to the route.
"""

import math

import numpy as np
import pytest

from sim import responder as R
from sim.world import World

PARKED = (-0.49, -1.24)
NORTH = [(-0.475, -1.225), (-0.475, -0.8)]


def _move(points, yaw, seconds=10):
    world = World(render=False)
    world._set_pose((-1.2, -1.7), 0.0)      # Scout parked out of the way
    r = R.Responder(world.m, world.d, clock=lambda: world.t)
    r._set_pose(PARKED, yaw)
    r.on_route({"id": "r", "robot": "responder", "cells": R.cells_along(points), "goal": "t",
                "model": "local-astar"})
    r.on_action({"action": "move", "route": "r", "item": "water"})
    for _ in range(int(seconds / 0.1)):
        r.step(0.1)
        world.tick(0.1)
        if r.state != "moving":
            break
    return r


@pytest.mark.parametrize("yaw", [math.pi / 2, 0.0, math.pi / 4, -math.pi / 2])
def test_parked_beside_b4_drives_north_without_a_block(yaw):
    r = _move(NORTH, yaw)
    assert r.state == "arrived", (r.state, r.last_hit, r.log[-1])
    assert not [d for d in r.log if d["outcome"] in ("blocked", "ray_hit")]
    # It ends in the route's goal cell, at most a cell off the goal centre.
    goal = R.cell_centre(R.cells_along(NORTH)[-1])
    assert float(np.linalg.norm(r.pos[:2] - goal)) < R.SKIP_NEAR


def test_far_start_is_unchanged():
    # Not parked on the first cell: the route's waypoints are the cell centres, untouched.
    world = World(render=False)
    r = R.Responder(world.m, world.d, clock=lambda: world.t)
    cells = R.cells_along([(-0.475, -1.225), (-0.475, -0.8)])
    r._set_pose((-0.9, -1.6), 0.0)
    path = r._start_path(cells)
    assert all(np.allclose(p, R.cell_centre(c)) for p, c in zip(path, cells, strict=True))


def test_offset_is_sideways_only_and_taken_up_at_the_turn():
    world = World(render=False)
    r = R.Responder(world.m, world.d, clock=lambda: world.t)
    cells = R.cells_along([(-0.475, -1.225), (-0.475, -1.125), (-0.325, -1.125)])
    r._set_pose(PARKED, math.pi / 2)
    path = r._start_path(cells)
    centres = [R.cell_centre(c) for c in cells]
    north = [p for p, c in zip(path, centres[1:], strict=False) if c[0] == centres[0][0]]
    assert north and all(abs(p[0] - PARKED[0]) < 1e-9 for p in north), "north run shifted onto the pose's x"
    assert np.allclose(path[-1], centres[-1]), "after the turn the route is the planner's again"
