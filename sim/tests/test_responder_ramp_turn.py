"""RAMP-R2-FIX: a turn on a ramp is not a block (ref #52).

On levels.xml the Responder drives east down ramp_r2 (L1 -> ground) with its collision rays tilted to the
ramp's full slope. At (2.775, 2.075) the B1 rescue route jogs 45 degrees north-east; along that heading
the ramp drops less steeply, so a ray still tilted for the old heading dives into ramp_r2 itself and the
Responder stopped "blocked" there with every supply still carried. The rays must tilt along the heading
they are cast on. Strict xfail until RAMP-RAY-FIX (Anthony's Claude-1, sim/responder.py) lands; then drop
the marks. The drive test also needs the Responder to leave the ramp at its foot (x 3.5), where on main a
nose-down ray meets the ground floor and stops it even on a straight run.
"""

import math

import pytest

from sim import responder as R
from sim.levels import LevelWorld

# The B1 rescue route's waypoints over ramp_r2 (tools/play.py run_rescue on main): east along y 2.075
# down the ramp, the 45 degree jog at x 2.775, then east along y 2.175 off the ramp onto the ground floor.
ROUTE = [(0.5, 2.075), (2.775, 2.075), (2.875, 2.175), (3.9, 2.175)]


RAMP_RAY_FIX = pytest.mark.xfail(strict=True, reason="RAMP-RAY-FIX: rays tilted for the old heading hit ramp_r2")


@pytest.fixture(scope="module")
def world():
    return LevelWorld(render=False)


def drive(world, r, seconds=60):
    for _ in range(int(seconds / 0.1)):
        r.step(0.1)
        world.tick(0.1)
        if r.state != "moving":
            break


@RAMP_RAY_FIX
def test_turn_on_ramp_r2_is_not_a_block(world):
    r = R.Responder(world.m, world.d, clock=lambda: world.t)
    r.floor_z = 0.6
    r._set_pose(ROUTE[0], 0.0)                           # on L1, clear of the walls, facing the ramp
    r.on_route({"id": "ramp", "robot": "responder", "cells": R.cells_along(ROUTE), "goal": "test",
                "model": "local-astar"})
    r.on_action({"action": "move", "route": "ramp"})
    drive(world, r)
    hits = [e["reason"] for e in r.log if e["outcome"] in ("ray_hit", "blocked")]
    assert r.state == "arrived", f"stopped {r.state} at {r.status()['pos']}: {hits}"
    assert not hits
    x, y = r.status()["pos"]
    assert math.hypot(x - ROUTE[-1][0], y - ROUTE[-1][1]) < 0.05
    assert abs(r.floor_z) < 0.01, f"ended at floor z {r.floor_z:.3f}, not on the ground floor"


@RAMP_RAY_FIX
def test_ray_tilt_follows_the_heading_it_is_cast_on(world):
    """Mid-ramp, facing east at ramp slope: the way north-east is clear (the ramp under it is no block)."""
    r = R.Responder(world.m, world.d, clock=lambda: world.t)
    r.floor_z = 0.6
    r._set_pose((1.2, 2.075), 0.0)                       # on L1, facing east, then step down the ramp
    for i in range(1, 60):
        r._set_pose((1.2 + i * 0.026, 2.075), 0.0)
    assert r.pitch > 0.25, "test setup: the chassis should be pitched down ramp_r2"
    assert r.free_ahead(math.pi / 4, 0.02), f"ramp read as a block: {r.last_hit}"
