"""L1 in the sim: a revoked move permit stops the Responder and blocks the route until re-earned."""

import numpy as np

from sim import demo_responder
from sim import responder as R
from sim.world import World


def setup():
    w = World(render=False)
    w._set_pose((-1.2, -1.7), 0.0)
    r = R.Responder(w.m, w.d, clock=lambda: w.t)
    r.on_route({"id": "r1", "robot": "responder", "cells": R.cells_along(demo_responder.ROUTES["r1"]),
                "goal": "test", "model": "local-astar"})
    return w, r


def run(w, r, seconds):
    for _ in range(int(seconds / 0.1)):
        r.step(0.1)
        w.tick(0.1)


def test_revoked_permit_stops_a_move_and_refuses_new_ones():
    w, r = setup()
    assert r.on_action({"action": "move", "route": "r1"})["outcome"] == "act"
    run(w, r, 1.0)
    where = np.array(r.pos)
    r.on_permit({"route": "r1", "granted": False, "t": 1.0, "reason": "LiDAR hit inside the route", "evidence": []})
    assert r.state == "frozen"
    run(w, r, 2.0)
    assert np.linalg.norm(np.array(r.pos) - where) < 1e-6  # it does not creep on
    out = r.on_action({"action": "move", "route": "r1"})
    assert out["outcome"] == "refused" and "revoked" in out["reason"]
    r.on_permit({"route": "r1", "granted": True, "t": 5.0, "reason": "re-earned by a fresh scan", "evidence": []})
    assert r.on_action({"action": "move", "route": "r1"})["outcome"] == "act"


def test_a_revoked_permit_on_another_route_does_not_stop_this_one():
    _, r = setup()
    r.on_action({"action": "move", "route": "r1"})
    r.on_permit({"route": "r9", "granted": False, "t": 1.0, "reason": "x", "evidence": []})
    assert r.state == "moving"
