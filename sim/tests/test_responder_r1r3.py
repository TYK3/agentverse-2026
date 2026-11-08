"""SUPPLY-RAY-R1R3: the Responder's collision ray must not stop it at the casualty it is delivering to.

Backup demo on main d7f7f64 (--auto-approve, GEMINI_MODE=off): route r3 stopped at [1.58, 0.73] with
"robot responder route r3 hit c1_g at [1.647, 0.896]", and B1 seed 3 stopped r7 on the same hit.
c1_g is the casualty's capsule (backup.xml), contype 0 / conaffinity 0: nothing collides with it, but
mj_ray ignores collision flags, so free_ahead read it as a wall and dropped the queued place/release.

A casualty never blocks the Responder. Other non-colliding geoms still do: x1_rubble (the block the
aftershock adds) is contype 0 as well, and the Responder must keep stopping for it.
"""

import math

import numpy as np

from sim import inject
from sim import responder as R
from sim.world import World

STOP = (1.58, 0.73)             # where r3 stopped in the demo
HIT = (1.647, 0.896)            # where its ray hit c1_g


def _responder(world, xy, heading):
    r = R.Responder(world.m, world.d, clock=lambda: world.t)
    r._set_pose(xy, heading)
    return r


def test_the_casualty_does_not_block_the_responder():
    world = World(render=False)
    world._set_pose((-1.2, -1.7), 0.0)          # Scout parked out of the way
    heading = math.atan2(HIT[1] - STOP[1], HIT[0] - STOP[0])
    r = _responder(world, STOP, heading)
    assert r.free_ahead(heading, 0.02), f"blocked by {r.last_hit}"


def test_a_non_colliding_block_still_blocks():
    world = World(render=False)
    world._set_pose((-1.2, -1.7), 0.0)
    assert inject.handle(world, {"kind": "block_added", "pos": [-0.625, -0.975, 0.3]})[0] == 200
    for _ in range(20):                          # x1 falls and settles flat
        world.tick(0.1)
    x1 = world.d.body("x1").xpos[:2]
    xy = np.array([x1[0] - 0.30, x1[1]])         # 0.30 m west of x1's centre, facing it
    r = _responder(world, xy, 0.0)
    assert not r.free_ahead(0.0, 0.05)
    assert r.last_hit[1] == "x1_rubble"
