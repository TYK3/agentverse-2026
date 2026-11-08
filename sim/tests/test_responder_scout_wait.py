"""SUPPLY-RAY-R1R3 cause 3: the Scout parked in the Responder's way is waited for, not re-planned around.

Backup demo on main + #452/#453: the Scout stood on the Responder's route at [1.31, 0.66] and the
collision ray stopped routes r1-r9, each a "blocked" that dropped the queued place/release, a full
re-plan about 5 s later, and a handoff that sent the Scout back to the Responder's spot. The Scout moves
on by itself, so the Responder now holds its pose and queue for up to SCOUT_WAIT_S and goes on when the
way is clear. Anything that is not the Scout still blocks at once.
"""

import math

from sim import responder as R
from sim.world import World

ROUTE = [(-0.48, -1.77), (-0.48, -1.15)]     # north from the Responder's start, clear of walls
SCOUT_IN_THE_WAY = (-0.48, -1.40)
SCOUT_OUT_OF_THE_WAY = (-1.2, -1.7)


def _setup(scout_xy):
    world = World(render=False)
    world._set_pose(scout_xy, -math.pi / 2)
    sent = []
    r = R.Responder(world.m, world.d, publish=lambda topic, data: sent.append((topic, data)),
                    clock=lambda: world.t)
    r.on_route({"id": "rs", "robot": "responder", "cells": R.cells_along(ROUTE), "goal": "test",
                "model": "local-astar"})
    r.on_action({"action": "move", "route": "rs", "item": "water"})
    r.on_action({"action": "place_supply", "route": "rs", "item": "water"})
    return world, r, sent


def _run(world, r, seconds, dt=0.1):
    for _ in range(int(seconds / dt)):
        r.step(dt)
        world.tick(dt)
        if r.state != "moving":
            break


def _outcomes(sent):
    return [d["outcome"] for t, d in sent if t == "log/decision"]


def test_the_responder_waits_for_the_scout_and_keeps_its_queue():
    world, r, sent = _setup(SCOUT_IN_THE_WAY)
    _run(world, r, 5.0)
    assert r.state == "moving", _outcomes(sent)
    assert _outcomes(sent).count("waiting") == 1
    assert "blocked" not in _outcomes(sent)
    assert [a["action"] for a in r.queue] == ["place_supply"]


def test_the_responder_goes_on_once_the_scout_moves():
    world, r, sent = _setup(SCOUT_IN_THE_WAY)
    _run(world, r, 3.0)
    assert r.state == "moving" and r.wait_since is not None
    world._set_pose(SCOUT_OUT_OF_THE_WAY, 0.0)
    _run(world, r, 10.0)
    assert r.state in ("arrived", "idle"), _outcomes(sent)
    assert "blocked" not in _outcomes(sent)
    assert any(d["reason"].startswith("placed water") for t, d in sent if t == "log/decision")


def test_a_scout_that_stays_is_still_a_block():
    world, r, sent = _setup(SCOUT_IN_THE_WAY)
    _run(world, r, R.SCOUT_WAIT_S + 3.0)
    assert r.state == "blocked"
    assert _outcomes(sent)[-2:] == ["ray_hit", "blocked"]
    assert "scout" in r.last_hit[1]


def test_a_wall_still_blocks_at_once():
    world, r, sent = _setup(SCOUT_OUT_OF_THE_WAY)
    r.on_route({"id": "rw", "robot": "responder",
                "cells": R.cells_along([(-0.48, -1.77), (-0.48, -0.6), (0.6, -0.6)]), "goal": "test",
                "model": "local-astar"})
    r.state, r.queue = "idle", []
    r.on_action({"action": "move", "route": "rw", "item": "water"})
    _run(world, r, 120.0)
    assert r.state == "blocked"
    assert "waiting" not in _outcomes(sent)
