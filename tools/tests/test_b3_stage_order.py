"""STAGE-ORDER-B3: a real B3 run log goes through its stages in order (ref b3).

The stages of a tools/run_b2.py --floor B3 log, each at the sim time it first happened:
  L1 -> ground -> B1 -> B2 -> B3   the descent, level by level, never climbing back
  shift                            the slab lands on the Scout's planned route, on B3
  stop                             the Scout stops for it: blocked, or the slab mapped from its own scan
  recheck                          the first ok route after the stop that misses the slab's core
  reached                          the summary: the Scout is beside c3 on B3
  verdict                          the run's own checks, last, all passed
`stages()` reads them from the records; the tests check the order and that time never goes back.

Which real log:
- always: REAL_B3, the stage records of a real run (seed 0 on main, 9/9 checks; poses and plans kept
  only around the shift, 225.0-226.6 s);
- also, when there is one: a full log from $B3_LOG, else the newest runs/b3-*.jsonl, else a fresh
  tools/run_b2.py --floor B3 run when MuJoCo is installed (about two minutes).
"""

import json
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
DESCENT = ["L1", "ground", "B1", "B2", "B3"]
ORDER = [*DESCENT, "shift", "stop", "recheck", "reached", "verdict"]

REAL_B3 = [
    {'t': 0.0, 'kind': 'level', 'level': 'L1'},
    {'t': 21.6, 'kind': 'level', 'level': 'ground'},
    {'t': 65.9, 'kind': 'level', 'level': 'B1'},
    {'t': 142.9, 'kind': 'level', 'level': 'B2'},
    {'t': 217.0, 'kind': 'level', 'level': 'B3'},
    {'t': 225.0, 'kind': 'pose', 'pos': [0.827, 0.473, -1.725], 'state': 'arrived', 'level': 'B3', 'cell': [16, 9, -36]},
    {'t': 225.0, 'kind': 'plan', 'status': 'explore', 'why': 'explore', 'target': [0.68, 0.62, -1.8], 'cells': [[16, 9, -36], [15, 10, -36], [14, 11, -36], [13, 12, -36], [13, 13, -36], [13, 14, -36], [12, 15, -36]]},
    {'t': 225.8, 'kind': 'plan', 'status': 'ok', 'why': 'route', 'target': [0.68, 1.43, -1.8], 'cells': [[13, 12, -36], [13, 13, -36], [13, 14, -36], [13, 15, -36], [13, 16, -36], [13, 17, -36], [13, 18, -36], [13, 19, -36], [13, 20, -36], [13, 21, -36], [13, 22, -36], [13, 23, -36], [13, 24, -36], [13, 25, -36], [13, 26, -36], [13, 27, -36], [13, 28, -36], [14, 29, -36], [14, 30, -36], [15, 31, -36], [15, 32, -36]]},
    {'t': 225.8, 'kind': 'shift', 'xy': [0.675, 0.925], 'level': 'B3', 'core': [[11, 16], [11, 17], [11, 18], [11, 19], [11, 20], [12, 16], [12, 17], [12, 18], [12, 19], [12, 20], [13, 16], [13, 17], [13, 18], [13, 19], [13, 20], [14, 16], [14, 17], [14, 18], [14, 19], [14, 20], [15, 16], [15, 17], [15, 18], [15, 19], [15, 20]], 'scout': [0.678, 0.622, -1.725]},
    {'t': 226.0, 'kind': 'mapped', 'cells': 4, 'sources': ['lidar', 'refused']},
    {'t': 226.0, 'kind': 'pose', 'pos': [0.678, 0.652, -1.725], 'state': 'blocked', 'level': 'B3', 'cell': [13, 13, -36]},
    {'t': 226.0, 'kind': 'plan', 'status': 'ok', 'why': 'route', 'target': [0.78, 0.57, -1.8], 'cells': [[13, 13, -36], [14, 12, -36], [15, 11, -36], [16, 12, -36], [17, 13, -36], [17, 14, -36], [18, 15, -36], [18, 16, -36], [18, 17, -36], [18, 18, -36], [18, 19, -36], [18, 20, -36], [18, 21, -36], [18, 22, -36], [18, 23, -36], [18, 24, -36], [18, 25, -36], [18, 26, -36], [17, 27, -36], [17, 28, -36], [16, 29, -36], [16, 30, -36], [16, 31, -36], [15, 32, -36]]},
    {'t': 226.5, 'kind': 'plan', 'status': 'ok', 'why': 'route', 'target': [0.82, 0.62, -1.8], 'cells': [[15, 11, -36], [16, 12, -36], [17, 12, -36], [18, 13, -36], [19, 14, -36], [19, 15, -36], [20, 16, -36], [20, 17, -36], [20, 18, -36], [20, 19, -36], [20, 20, -36], [20, 21, -36], [19, 22, -36], [18, 23, -36], [17, 24, -36], [16, 25, -36], [15, 26, -36], [15, 27, -36], [15, 28, -36], [15, 29, -36], [15, 30, -36], [15, 31, -36], [15, 32, -36]]},
    {'t': 230.9, 'kind': 'summary', 'floor': 'B3', 'reached': True, 'final_pos': [0.825, 1.525, -1.725], 'final_level': 'B3', 'max_jump': 0.0313, 'route': 'ok', 'route_k': [12, -36]},
    {'t': 230.9, 'kind': 'verdict', 'steps': {'descended level by level to the target floor': {'ok': True, 't': None, 'detail': 'L1 -> ground -> B1 -> B2 -> B3'}, 'slab dropped on the planned route on the target floor': {'ok': True, 't': 225.8, 'detail': 'slab at [0.675, 0.925] on B3'}, 'Scout stopped short of the slab': {'ok': True, 't': 226.0, 'detail': 'state blocked'}, "slab mapped from the Scout's own measurements": {'ok': True, 't': 226.0, 'detail': "4 occupied cell(s) in the slab's footprint (lidar, refused)"}, 're-planned route avoids the slab': {'ok': True, 't': 226.0, 'detail': '6/6 planned paths after the shift avoid it'}, 'Scout reached the casualty on the target floor': {'ok': True, 't': 230.9, 'detail': 'at [0.825, 1.525, -1.725] on B3'}, 'Scout never entered the slab': {'ok': True, 't': None, 'detail': 'never inside it'}, 'no teleport': {'ok': True, 't': None, 'detail': 'max move 0.0313 m per tick'}, 'route over the scouted map from L1 to the target floor': {'ok': True, 't': None, 'detail': 'ok k [12, -36]'}}, 'passed': ['descended level by level to the target floor', 'slab dropped on the planned route on the target floor', 'Scout stopped short of the slab', "slab mapped from the Scout's own measurements", 're-planned route avoids the slab', 'Scout reached the casualty on the target floor', 'Scout never entered the slab', 'no teleport', 'route over the scouted map from L1 to the target floor'], 'failed': []},
]


def stages(records):
    """[(stage, t)] in the order the stages first happened (see the module docstring)."""
    out, seen = [], set()

    def hit(stage, t):
        if stage not in seen:
            seen.add(stage)
            out.append((stage, t))

    shift = stop = None
    core = set()
    for r in records:
        kind, t = r.get("kind"), r.get("t")
        if kind == "level" and r.get("level") in DESCENT:
            hit(r["level"], t)
        elif kind == "shift" and shift is None:
            shift, core = t, {tuple(c) for c in r.get("core", [])}
            hit("shift", t)
        elif shift is not None and stop is None and (kind == "mapped" or (kind == "pose" and r.get("state") == "blocked")):
            stop = t
            hit("stop", t)
        elif (kind == "plan" and stop is not None and r.get("status") == "ok"
              and not core & {tuple(c[:2]) for c in r.get("cells", [])}):
            hit("recheck", t)
        elif kind == "summary" and r.get("reached") is True and r.get("final_level") == "B3":
            hit("reached", t)
        elif kind == "verdict" and not r.get("failed"):
            hit("verdict", t)
    return out


def check_order(records):
    got = stages(records)
    assert [s for s, _ in got] == ORDER, got
    times = [t for _, t in got]
    assert times == sorted(times), got
    levels = [r["level"] for r in records if r.get("kind") == "level"]
    assert levels == DESCENT, f"climbed back or skipped a level: {levels}"
    assert records[-1]["kind"] == "verdict", "the verdict is the last record"
    return dict(got)


def test_real_b3_log_stages_in_order():
    t = check_order(REAL_B3)
    assert (t["shift"], t["stop"], t["recheck"], t["reached"]) == (225.8, 226.0, 226.0, 230.9)
    assert t["B3"] < t["shift"]                      # the slab lands after the Scout is on B3


def _real_log():
    env = os.environ.get("B3_LOG")
    if env:
        return pathlib.Path(env)
    found = sorted((ROOT / "runs").glob("b3-*.jsonl"), key=lambda p: p.stat().st_mtime)
    if found:
        return found[-1]
    pytest.importorskip("mujoco")
    from tools.run_b2 import run

    _verdict, path = run(seed=0, floor="B3", out_dir=ROOT / "runs")
    return path


def test_full_real_b3_log_stages_in_order():
    path = _real_log()
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    t = check_order(records)
    print(f"{path.name}: " + ", ".join(f"{s} {t[s]}" for s in ORDER))


# The stage reader itself, on hand-made logs: each broken order is caught.
def _log(*kinds):
    recs, t = [], 0.0
    for k in kinds:
        t += 1.0
        if k in DESCENT:
            recs.append({"t": t, "kind": "level", "level": k})
        elif k == "shift":
            recs.append({"t": t, "kind": "shift", "level": "B3", "core": [[5, 5]]})
        elif k == "stop":
            recs.append({"t": t, "kind": "pose", "state": "blocked"})
        elif k == "through":
            recs.append({"t": t, "kind": "plan", "status": "ok", "cells": [[5, 5, -36]]})
        elif k == "recheck":
            recs.append({"t": t, "kind": "plan", "status": "ok", "cells": [[4, 4, -36]]})
        elif k == "reached":
            recs.append({"t": t, "kind": "summary", "reached": True, "final_level": "B3"})
        elif k == "verdict":
            recs.append({"t": t, "kind": "verdict", "failed": []})
    return recs


def test_a_clean_order_passes():
    check_order(_log(*ORDER))


@pytest.mark.parametrize("kinds", [
    [*DESCENT, "recheck", "shift", "stop", "reached", "verdict"],          # a route before any stop is no recheck
    [*DESCENT, "shift", "stop", "through", "reached", "verdict"],          # through the slab is no recheck
    [*DESCENT, "shift", "recheck", "reached", "verdict"],                  # never stopped
    ["L1", "ground", "B1", "B3", "shift", "stop", "recheck", "reached", "verdict"],   # skipped B2
    [*DESCENT, "shift", "stop", "recheck", "verdict", "reached"],          # verdict not last
])
def test_broken_orders_fail(kinds):
    with pytest.raises(AssertionError):
        check_order(_log(*kinds))


def test_climbing_back_fails():
    with pytest.raises(AssertionError):
        check_order(_log("L1", "ground", "B1", "B2", "B1", "B2", "B3", "shift", "stop", "recheck", "reached", "verdict"))
