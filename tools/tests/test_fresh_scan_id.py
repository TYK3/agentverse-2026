"""FRESH-SCAN-ID: each fresh_scan that re-grants a move permit names the one revocation it lifts.

planner/permit.py (L1) revokes a route's permit on a sensed change (a "shift" or "hazard" evidence entry) and
re-grants it only by a fresh LiDAR scan of every route cell (a "fresh_scan" entry, "all N route cells seen
free by LiDAR after the change at X s"). Evidence entries carry no id of their own, so a fresh scan is
identified by its route (the permit/route message) and the change time in its detail. Over the stream of
permit/route messages this checks that every fresh_scan:

  - is the newest evidence entry of a granted message for its route;
  - follows a revocation of that same route (granted false, newest entry shift or hazard) since the last
    grant, at or before its own time;
  - names exactly that revocation: "change at X s" is the revocation's time (to the 0.1 s it prints);
  - counts the route's own cells ("all N route cells");

and that each revocation is lifted by at most one fresh_scan, and evidence lists only ever grow (a message's
evidence starts with the previous message's for that route).

The stream comes from the real permit rule fed real MuJoCo LiDAR on B1 (as test_b1_permit_relook.py): one
route is revoked by a slab and re-earned twice, a second route by a hazard. Broken copies of the stream fail.
"""

import copy
import re

import pytest

pytest.importorskip("mujoco")

import mujoco

from planner.permit import Permits, columns
from sim.levels import LevelWorld
from tools.run_b2 import drop_slab, scene_with_slab

CHANGE = re.compile(r"^all (\d+) route cells seen free by LiDAR after the change at (\d+(?:\.\d+)?)s$")
REVOKERS = ("shift", "hazard")


def fresh_scan_problems(messages, routes):
    """Every way a fresh_scan is not tied to the revocation it lifts; `routes` maps route id -> cells."""
    bad, last, pending, lifted = [], {}, {}, set()
    for n, m in enumerate(messages):
        route, ev = m["route"], m["evidence"]
        where = f"message {n} ({route} at t={m['t']})"
        prev = last.get(route)
        if prev is not None and ev[:len(prev)] != prev:
            bad.append(f"{where}: evidence does not extend the previous message's")
        new = ev[len(prev or []):]
        last[route] = ev
        for e in new:
            if e["kind"] in REVOKERS and not m["granted"]:
                pending[route] = e["t"]
            elif e["kind"] == "fresh_scan":
                if not m["granted"] or e is not ev[-1]:
                    bad.append(f"{where}: fresh_scan is not the newest entry of a granted message")
                match = CHANGE.match(e["detail"])
                if not match:
                    bad.append(f"{where}: fresh_scan detail {e['detail']!r} names no change")
                    continue
                count, change = int(match.group(1)), float(match.group(2))
                revoked = pending.pop(route, None)
                if revoked is None:
                    bad.append(f"{where}: fresh_scan at t={e['t']} lifts no revocation of {route}"
                               + (" (already lifted)" if (route, change) in lifted else ""))
                    continue
                if abs(change - round(revoked, 1)) > 1e-9:
                    bad.append(f"{where}: fresh_scan names the change at {change}s, but {route} "
                               f"was revoked at {revoked}s")
                if e["t"] < revoked:
                    bad.append(f"{where}: fresh_scan at t={e['t']} is before the revocation at {revoked}s")
                if count != len(columns(routes[route])):
                    bad.append(f"{where}: fresh_scan counts {count} cells, {route} has {len(columns(routes[route]))}")
                lifted.add((route, change))
    return bad


def _move_slab(world, xyz):
    body = world.m.body("x1").id
    adr = world.m.jnt_qposadr[world.m.body_jntadr[body]]
    world.d.qpos[adr:adr + 3] = xyz
    mujoco.mj_forward(world.m, world.d)


@pytest.fixture(scope="module")
def stream(tmp_path_factory):
    world = LevelWorld(path=scene_with_slab(tmp_path_factory.mktemp("scene")), render=False)
    world._set_pose((0.4, 1.45), 0.0)
    world._set_z(-0.6)
    mujoco.mj_forward(world.m, world.d)
    assert world.level() == "B1"
    routes = {"b1-water": [[i, 29, -12] for i in range(10, 25)],      # east along y 1.45, through the slab
              "b1-kit": [[8, j, -12] for j in range(20, 27)]}         # a second route, west of the Scout
    permits, out = Permits(), []

    def feed(pairs):
        out.extend(data for topic, data in pairs if topic == "permit/route")

    for rid, cells in routes.items():
        permits.on_route_proposed({"id": rid, "cells": cells})
        feed(permits.on_route_verified({"id": rid, "ok": True}, 1.0))
    for shift_t, clear_t in ((2.0, 21.0), (30.3, 41.7)):              # the slab lands, is seen, then is gone
        drop_slab(world, (1.0, 1.45), -0.6)
        feed(permits.on_sensors(world.sensors_message(camera=False), shift_t))
        assert not permits.granted("b1-water")
        _move_slab(world, [-3.0, -3.0, -3.0])
        feed(permits.on_sensors(world.sensors_message(camera=False), clear_t))
        assert permits.granted("b1-water")
    hazard = [{"cell": [8, 23, -12], "status": "at_risk", "why": "unsupported wall", "estimate": True}]
    feed(permits.on_hazards(hazard, 50.0))
    assert not permits.granted("b1-kit")
    feed(permits.on_hazards([], 55.0))
    feed(permits.on_sensors(world.sensors_message(camera=False), 56.4))
    return out, routes, permits


def test_each_fresh_scan_names_the_revocation_it_lifts(stream):
    messages, routes, permits = stream
    fresh = [(m["route"], m["evidence"][-1]["detail"]) for m in messages
             if m["granted"] and m["evidence"][-1]["kind"] == "fresh_scan"]
    assert fresh == [
        ("b1-water", "all 15 route cells seen free by LiDAR after the change at 2.0s"),
        ("b1-water", "all 15 route cells seen free by LiDAR after the change at 30.3s"),
        ("b1-kit", "all 7 route cells seen free by LiDAR after the change at 50.0s"),
    ], fresh
    assert permits.granted("b1-water") and permits.granted("b1-kit")
    assert fresh_scan_problems(messages, routes) == []


def _fresh(messages):
    return [m for m in messages if m["granted"] and m["evidence"][-1]["kind"] == "fresh_scan"]


def _wrong_change_time(msgs):
    e = _fresh(msgs)[1]["evidence"][-1]
    e["detail"] = e["detail"].replace("30.3s", "2.0s")


def _no_revocation(msgs):
    first_revoke = next(i for i, m in enumerate(msgs) if not m["granted"])
    del msgs[first_revoke]
    for m in msgs:          # drop the entry everywhere, so the evidence lists still extend each other
        m["evidence"] = [e for e in m["evidence"] if not (e["kind"] == "shift" and e["t"] == 2.0)]


def _twice(msgs):
    m = copy.deepcopy(_fresh(msgs)[0])
    msgs.insert(msgs.index(_fresh(msgs)[0]) + 1, m)
    m["evidence"].append(copy.deepcopy(m["evidence"][-1]))


def _wrong_count(msgs):
    e = _fresh(msgs)[2]["evidence"][-1]
    e["detail"] = e["detail"].replace("all 7", "all 15")


def _fresh_in_revoked_message(msgs):
    _fresh(msgs)[0]["granted"] = False


def _other_route(msgs):
    _fresh(msgs)[2]["route"] = "b1-water"


def _rewritten_history(msgs):
    # Messages share evidence dicts (Permit.message copies the list, not the entries): edit a private copy.
    m = _fresh(msgs)[1]
    m["evidence"] = copy.deepcopy(m["evidence"])
    m["evidence"][0]["detail"] = "physics check passed for 99 cells"


BROKEN = {
    "names the wrong change": (_wrong_change_time, "names the change at 2.0s"),
    "lifts no revocation": (_no_revocation, "lifts no revocation"),
    "one revocation lifted twice": (_twice, "lifts no revocation"),
    "counts another route's cells": (_wrong_count, "counts 15 cells"),
    "fresh scan in a revoked message": (_fresh_in_revoked_message, "not the newest entry of a granted"),
    "fresh scan on a route never revoked there": (_other_route, "does not extend"),
    "earlier evidence rewritten": (_rewritten_history, "does not extend"),
}


@pytest.mark.parametrize("name", BROKEN)
def test_a_broken_fresh_scan_is_caught(stream, name):
    messages, routes, _ = stream
    change, expect = BROKEN[name]
    msgs = copy.deepcopy(messages)
    change(msgs)
    bad = fresh_scan_problems(msgs, routes)
    assert any(expect in line for line in bad), f"{name}: not caught; found {bad}"
