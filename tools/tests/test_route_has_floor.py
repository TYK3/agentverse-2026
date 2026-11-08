"""ROUTE-HAS-FLOOR: every route a real run plans names the floor it is for.

- tools/run_levels.py (chained B1 > B2 > B3, seed 0): every "plan" record has a `leg` naming its target
  floor (B1, B2 or B3), legs come in that order and never go back, every plan of a leg comes before
  that leg's "leg" record, and its target height is on L1..B3 (a level or a ramp between two).
- tools/run_b2.py (B2, seed 0): every planned path ends on a named level (L1, ground, B1, B2, B3) or on
  a ramp between two of them, and every route to the goal (status ok) ends on B2.
Synthetic records pin the checks. Skips the real runs without MuJoCo.
"""

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

RES = 0.05
LEVEL_K = {"L1": 12, "ground": 0, "B1": -12, "B2": -24, "B3": -36}   # floor height / RES (sim/levels.py)
K_TOL = 3
LEGS = ("B1", "B2", "B3")


def floor_name(k):
    """Level name for a cell height k, "ramp" between two levels, None outside the building."""
    for name, lk in LEVEL_K.items():
        if abs(k - lk) <= K_TOL:
            return name
    lo, hi = min(LEVEL_K.values()), max(LEVEL_K.values())
    return "ramp" if lo < k < hi else None


def leg_problems(records):
    """[str] for plan records that do not name a leg, go back a leg, or come after their leg ended."""
    out, seen, ended = [], -1, set()
    for r in records:
        if r["kind"] == "leg":
            ended.add(r["floor"])
        if r["kind"] != "plan":
            continue
        leg = r.get("leg")
        if leg not in LEGS:
            out.append(f"{r['t']}: plan names no floor ({leg!r})")
            continue
        if LEGS.index(leg) < seen:
            out.append(f"{r['t']}: plan for {leg} after a later leg")
        if leg in ended:
            out.append(f"{r['t']}: plan for {leg} after that leg ended")
        seen = max(seen, LEGS.index(leg))
        if floor_name(round(r["target"][2] / RES)) is None:
            out.append(f"{r['t']}: target {r['target']} is on no floor")
    return out


def path_problems(records, floor):
    """[str] for planned paths that end on no floor, and goal routes that end off `floor`."""
    out = []
    for r in records:
        if r["kind"] != "plan" or not r.get("cells"):
            continue
        name = floor_name(r["cells"][-1][2])
        if name is None:
            out.append(f"{r['t']}: path ends on no floor at {r['cells'][-1]}")
        elif r.get("status") == "ok" and name != floor:
            out.append(f"{r['t']}: route to the goal ends on {name}, not {floor}")
    return out


def test_floor_name_levels_ramps_and_outside():
    assert [floor_name(k) for k in (12, 1, -13, -26, -36, -6, 20, -40)] == \
        ["L1", "ground", "B1", "B2", "B3", "ramp", None, None]


def test_leg_problems_flags_each_case():
    recs = [{"t": 0, "kind": "plan", "leg": "B1", "target": [0, 0, 0.6]},
            {"t": 1, "kind": "plan", "target": [0, 0, 0.0]},
            {"t": 2, "kind": "plan", "leg": "B2", "target": [0, 0, -1.2]},
            {"t": 3, "kind": "plan", "leg": "B1", "target": [0, 0, -0.6]},
            {"t": 4, "kind": "leg", "floor": "B2"},
            {"t": 5, "kind": "plan", "leg": "B2", "target": [0, 0, -1.2]},
            {"t": 6, "kind": "plan", "leg": "B3", "target": [0, 0, -3.0]}]
    assert leg_problems(recs) == ["1: plan names no floor (None)", "3: plan for B1 after a later leg",
                                  "5: plan for B2 after that leg ended", "6: target [0, 0, -3.0] is on no floor"]


def test_path_problems_flags_off_floor_goal_routes():
    recs = [{"t": 0, "kind": "plan", "status": "explore", "cells": [[0, 0, -6]]},
            {"t": 1, "kind": "plan", "status": "ok", "cells": [[0, 0, -12]]},
            {"t": 2, "kind": "plan", "status": "explore", "cells": [[0, 0, 30]]},
            {"t": 3, "kind": "plan", "status": "ok", "cells": [[0, 0, -24]]}]
    assert path_problems(recs, "B2") == ["1: route to the goal ends on B1, not B2", "2: path ends on no floor at [0, 0, 30]"]


def test_real_chained_run_plans_name_their_floor():
    pytest.importorskip("mujoco")
    import run_levels

    records = run_levels.run(seed=0)
    plans = [r for r in records if r["kind"] == "plan"]
    assert {r.get("leg") for r in plans} == set(LEGS)
    assert leg_problems(records) == []


def test_real_b2_paths_end_on_a_floor(tmp_path):
    pytest.importorskip("mujoco")
    import run_b2

    _, path = run_b2.run(seed=0, out_dir=tmp_path, floor="B2")
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert any(r["kind"] == "plan" and r.get("status") == "ok" for r in records)
    assert path_problems(records, "B2") == []
