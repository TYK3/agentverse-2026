"""RECHECK-PLAN-NEW: after the slab shift and the recheck that maps it, the Scout plans a new route.

One real B2 rescue (tools/run_b2.py, seed 0): the route the Scout was driving when the slab dropped
is compared with the first route planned after the slab got into the map ("mapped" record). The new
one must come after the recheck, within STOP_WINDOW of the shift, be a different route (other cells,
not a prefix of the old one), and keep the same goal
(staying off the slab is PLAN-AVOIDS-SHIFT). A synthetic log pins the
helper itself. Skips the real run without MuJoCo.
"""

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def routes_around_recheck(records):
    """(route driven at the shift, first route after the recheck, shift, mapped); None where missing."""
    shift = next((r for r in records if r["kind"] == "shift"), None)
    mapped = next((r for r in records if r["kind"] == "mapped"), None)
    if shift is None or mapped is None:
        return None, None, shift, mapped
    routes = [r for r in records if r["kind"] == "plan" and r.get("status") == "ok" and r.get("cells")]
    old = next((r for r in reversed(routes) if r["t"] <= shift["t"]), None)
    new = next((r for r in routes if r["t"] >= mapped["t"] and r is not old), None)
    return old, new, shift, mapped


def cells(plan):
    return [tuple(c) for c in plan["cells"]]


SYNTH = [
    {"t": 1.0, "kind": "plan", "status": "ok", "why": "route", "cells": [[0, 0, -24], [1, 0, -24], [2, 0, -24]]},
    {"t": 1.0, "kind": "shift", "xy": [0.075, 0.025], "core": [[1, 0]], "footprint": [[1, 0]]},
    {"t": 1.1, "kind": "mapped", "cells": 1, "sources": ["lidar"]},
    {"t": 1.1, "kind": "plan", "status": "ok", "why": "route", "cells": [[0, 0, -24], [0, 1, -24], [1, 1, -24],
                                                                         [2, 1, -24], [2, 0, -24]]},
]


def test_helper_picks_the_driven_route_and_the_first_one_after_the_recheck():
    old, new, shift, mapped = routes_around_recheck(SYNTH)
    assert old is SYNTH[0] and new is SYNTH[3] and shift is SYNTH[1] and mapped is SYNTH[2]


def test_helper_reports_no_new_route_without_a_recheck():
    old, new, _, mapped = routes_around_recheck([r for r in SYNTH if r["kind"] != "mapped"])
    assert mapped is None and old is None and new is None


@pytest.fixture(scope="module")
def records(tmp_path_factory):
    pytest.importorskip("mujoco")
    import run_b2

    _, path = run_b2.run(seed=0, out_dir=tmp_path_factory.mktemp("recheck"), floor="B2")
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_real_recheck_gives_a_new_route(records):
    import run_b2

    old, new, shift, mapped = routes_around_recheck(records)
    assert shift is not None, "no slab shift in the B2 run"
    assert mapped is not None, "the slab never got into the map"
    assert old is not None, "no route was being driven at the shift"
    assert new is not None, "no route planned after the recheck"
    assert new["t"] >= mapped["t"] >= shift["t"]
    assert new["t"] <= shift["t"] + run_b2.STOP_WINDOW, "the new route came too late after the shift"
    a, b = cells(old), cells(new)
    assert a != b and b != a[:len(b)], "the route after the recheck is the old one"
    assert a[-1] == b[-1], "the new route should end at the same goal"

