"""PLAN-AVOIDS-SHIFT: once the slab is in the map, no planned route goes over it, and the Scout never
drives into it.

Real rescues with a slab shift (tools/run_b2.py --floor B2 and B3, seed 0). Every route planned after
the slab was mapped ("mapped" record) is checked cell by cell against the slab's core footprint on the
slab's floor, and every pose after the shift against the same cells. Synthetic logs pin the check (a
route over the slab, a pose in it, a route over the same x, y on another floor). Skips the real runs
without MuJoCo.
"""

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

K_TOL = 3   # cells of height: a route cell this close to the slab's floor is on that floor
FLOOR_K = {"B1": -12, "B2": -24, "B3": -36}   # floor height / 0.05, as tools/run_b2.py


def violations(records):
    """[(t, what)] for each route cell (after the slab is mapped) or pose (after the shift) on the slab."""
    shift = next((r for r in records if r["kind"] == "shift"), None)
    mapped = next((r for r in records if r["kind"] == "mapped"), None)
    if shift is None:
        return []
    core = {tuple(c) for c in shift["core"]}
    k = shift.get("k", FLOOR_K.get(shift.get("level")))   # run_b2 logs the level, not k
    out = []
    for r in records:
        if r["kind"] == "plan" and mapped and r["t"] >= mapped["t"] and r.get("status") == "ok":
            hits = [c for c in r.get("cells") or [] if tuple(c[:2]) in core and (k is None or abs(c[2] - k) <= K_TOL)]
            if hits:
                out.append((r["t"], f"route over the slab at {hits[0]}"))
        if r["kind"] == "pose" and r["t"] >= shift["t"] and tuple(r["cell"][:2]) in core:
            out.append((r["t"], f"pose in the slab at {r['cell']}"))
    return out


def log(*extra):
    base = [
        {"t": 1.0, "kind": "shift", "xy": [0.075, 0.025], "core": [[1, 0]], "footprint": [[1, 0]], "level": "B2"},
        {"t": 1.1, "kind": "mapped", "cells": 1, "sources": ["lidar"]},
        {"t": 1.1, "kind": "plan", "status": "ok", "cells": [[0, 0, -24], [0, 1, -24], [1, 1, -24], [2, 0, -24]]},
        {"t": 2.0, "kind": "pose", "cell": [0, 1, -24]},
    ]
    return sorted(base + list(extra), key=lambda r: r["t"])


def test_a_route_round_the_slab_passes():
    assert violations(log()) == []


def test_a_route_over_the_slab_after_it_is_mapped_fails():
    bad = {"t": 1.5, "kind": "plan", "status": "ok", "cells": [[0, 0, -24], [1, 0, -24], [2, 0, -24]]}
    assert violations(log(bad)) == [(1.5, "route over the slab at [1, 0, -24]")]


def test_a_route_planned_before_the_slab_was_mapped_is_not_counted():
    early = {"t": 0.5, "kind": "plan", "status": "ok", "cells": [[1, 0, -24]]}
    assert violations(log(early)) == []


def test_same_x_y_on_another_floor_is_not_the_slab():
    other = {"t": 1.5, "kind": "plan", "status": "ok", "cells": [[1, 0, -12]]}
    assert violations(log(other)) == []


def test_a_pose_inside_the_slab_fails():
    assert violations(log({"t": 2.5, "kind": "pose", "cell": [1, 0, -24]})) == [(2.5, "pose in the slab at [1, 0, -24]")]


@pytest.mark.parametrize("floor", ["B2", "B3"])
def test_real_routes_avoid_the_shifted_slab(floor, tmp_path):
    pytest.importorskip("mujoco")
    import run_b2

    verdict, path = run_b2.run(seed=0, out_dir=tmp_path, floor=floor)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    shift = next((r for r in records if r["kind"] == "shift"), None)
    mapped = next((r for r in records if r["kind"] == "mapped"), None)
    assert shift is not None and mapped is not None, f"no shift or no mapped slab on {floor}"
    after = [r for r in records if r["kind"] == "plan" and r.get("status") == "ok" and r["t"] >= mapped["t"]]
    assert after, "no route planned after the slab was mapped"
    assert violations(records) == []
    assert "Scout reached the casualty on the target floor" in verdict["passed"]
