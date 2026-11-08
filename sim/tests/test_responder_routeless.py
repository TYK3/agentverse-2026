"""A route-less place_supply never sets a supply down (e2e on main a7e2b11).

Building scene: at t 0.7 s a place_supply with route "none" put the water down at the Responder's start,
and all 85 routes after it hit water_supply. Tower: 95 route-less commands, 79 refusals. The Responder
now ignores them (no refusal, so the queued delivery behind them survives) and logs it once.
"""

from sim import responder as R
from sim.world import World

ROUTE = [(-0.48, -1.77), (-0.48, -1.15)]


def _responder():
    world = World(render=False)
    world._set_pose((-1.2, -1.7), 0.0)
    sent = []
    r = R.Responder(world.m, world.d, publish=lambda topic, data: sent.append((topic, data)),
                    clock=lambda: world.t)
    return world, r, sent


def _decisions(sent):
    return [d for t, d in sent if t == "log/decision"]


def test_a_routeless_place_supply_keeps_the_water_on_board():
    _, r, sent = _responder()
    for _ in range(3):
        r.on_action({"action": "place_supply", "route": "none", "item": "water"})
    assert r.holding("water")
    assert [d["outcome"] for d in _decisions(sent)] == ["ignored"]
    assert not any(d["reason"].startswith("placed") for d in _decisions(sent))


def test_the_queued_delivery_survives_routeless_commands():
    world, r, sent = _responder()
    r.on_route({"id": "rq", "robot": "responder", "cells": R.cells_along(ROUTE), "goal": "test",
                "model": "local-astar"})
    r.on_action({"action": "move", "route": "rq", "item": "water"})
    r.on_action({"action": "place_supply", "route": "none", "item": "water"})
    r.on_action({"action": "place_supply", "route": "rq", "item": "water"})
    for _ in range(100):
        r.step(0.1)
        world.tick(0.1)
        if r.state != "moving":
            break
    assert r.state == "arrived"
    assert not r.holding("water")
    assert sum(d["reason"].startswith("placed water") for d in _decisions(sent)) == 1
    assert "refused" not in [d["outcome"] for d in _decisions(sent)]
