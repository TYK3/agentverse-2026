"""SHIFT-THEN-RECHECK-B2: a real B2 run log has a slab shift and, after it, a recheck (ref b2).

In a tools/run_b2.py --floor B2 log:
- shift:   a `shift` record on B2, after the Scout reached B2;
- recheck: the first `plan` strictly after the shift with status ok whose cells miss the slab's core
           (the route planned at the shift's own instant is the one the slab landed on: never counted);
- evidence: the slab is `mapped` from the Scout's own lidar/refused step by the time of the recheck;
- after:   every later ok route misses the slab too, and the Scout reaches c2 on B2 after the recheck.
The logged stop pose is not required before the recheck: run_b2 logs poses at 1 Hz, and on B2 the
re-plan comes 0.1 s after the shift, before the next pose line (175.0 s here).

Real log: REAL_B2 (seed 0 on main, 9/9: the level, shift, mapped, summary and verdict records, plus poses
and plans 173.0-175.0 s), and, when available, a full log from $B2_LOG or the newest runs/b2-*.jsonl
(it skips otherwise; CI has neither).
"""

import json
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
MEASURED = {"lidar", "refused"}

REAL_B2 = [
    {'t': 0.0, 'kind': 'level', 'level': 'L1'},
    {'t': 21.6, 'kind': 'level', 'level': 'ground'},
    {'t': 80.1, 'kind': 'level', 'level': 'B1'},
    {'t': 155.3, 'kind': 'level', 'level': 'B2'},
    {'t': 173.0, 'kind': 'pose', 'pos': [1.501, 1.001, -1.125], 'state': 'arrived', 'level': 'B2', 'cell': [30, 20, -24]},
    {'t': 173.0, 'kind': 'plan', 'status': 'explore', 'why': 'probe', 'target': [1.39, 1.11, -1.2], 'cells': [[30, 20, -24], [29, 20, -24]]},
    {'t': 173.6, 'kind': 'plan', 'status': 'ok', 'why': 'route', 'target': [1.23, 0.97, -1.2], 'cells': [[27, 22, -24], [26, 21, -24], [25, 20, -24], [24, 19, -24], [23, 19, -24], [22, 19, -24], [21, 19, -24], [20, 19, -24], [19, 19, -24], [18, 19, -24], [17, 18, -24], [16, 17, -24], [15, 16, -24]]},
    {'t': 173.6, 'kind': 'shift', 'xy': [1.125, 0.975], 'level': 'B2', 'core': [[20, 17], [20, 18], [20, 19], [20, 20], [20, 21], [21, 17], [21, 18], [21, 19], [21, 20], [21, 21], [22, 17], [22, 18], [22, 19], [22, 20], [22, 21], [23, 17], [23, 18], [23, 19], [23, 20], [23, 21], [24, 17], [24, 18], [24, 19], [24, 20], [24, 21]], 'scout': [1.395, 1.107, -1.125]},
    {'t': 173.7, 'kind': 'mapped', 'cells': 5, 'sources': ['lidar', 'refused']},
    {'t': 173.7, 'kind': 'plan', 'status': 'ok', 'why': 'route', 'target': [1.48, 1.18, -1.2], 'cells': [[27, 22, -24], [28, 22, -24], [29, 23, -24], [30, 22, -24], [30, 21, -24], [31, 20, -24], [30, 19, -24], [29, 18, -24], [28, 17, -24], [27, 16, -24], [26, 15, -24], [25, 14, -24], [24, 13, -24], [23, 13, -24], [22, 13, -24], [21, 13, -24], [20, 14, -24], [19, 14, -24], [18, 15, -24], [17, 15, -24], [16, 15, -24], [15, 16, -24]]},
    {'t': 174.0, 'kind': 'pose', 'pos': [1.463, 1.165, -1.125], 'state': 'moving', 'level': 'B2', 'cell': [29, 23, -24]},
    {'t': 174.1, 'kind': 'plan', 'status': 'ok', 'why': 'route', 'target': [1.52, 1.12, -1.2], 'cells': [[29, 23, -24], [30, 22, -24], [30, 21, -24], [31, 20, -24], [30, 19, -24], [30, 18, -24], [29, 17, -24], [28, 16, -24], [27, 15, -24], [26, 14, -24], [25, 13, -24], [24, 12, -24], [23, 12, -24], [22, 13, -24], [21, 13, -24], [20, 14, -24], [19, 14, -24], [18, 15, -24], [17, 15, -24], [16, 15, -24], [15, 16, -24]]},
    {'t': 174.4, 'kind': 'plan', 'status': 'ok', 'why': 'route', 'target': [1.52, 1.07, -1.2], 'cells': [[30, 22, -24], [30, 21, -24], [31, 20, -24], [30, 19, -24], [30, 18, -24], [29, 17, -24], [28, 16, -24], [27, 15, -24], [26, 14, -24], [25, 13, -24], [24, 12, -24], [23, 12, -24], [22, 13, -24], [21, 13, -24], [20, 14, -24], [19, 14, -24], [18, 15, -24], [17, 15, -24], [16, 15, -24], [15, 16, -24]]},
    {'t': 174.7, 'kind': 'plan', 'status': 'ok', 'why': 'route', 'target': [1.57, 1.02, -1.2], 'cells': [[30, 21, -24], [31, 20, -24], [30, 19, -24], [30, 18, -24], [29, 17, -24], [28, 16, -24], [27, 15, -24], [26, 14, -24], [25, 13, -24], [24, 12, -24], [23, 12, -24], [22, 13, -24], [21, 13, -24], [20, 14, -24], [19, 14, -24], [18, 15, -24], [17, 15, -24], [16, 15, -24], [15, 16, -24]]},
    {'t': 175.0, 'kind': 'pose', 'pos': [1.567, 1.033, -1.125], 'state': 'arrived', 'level': 'B2', 'cell': [31, 20, -24]},
    {'t': 175.0, 'kind': 'plan', 'status': 'ok', 'why': 'route', 'target': [1.52, 0.97, -1.2], 'cells': [[31, 20, -24], [30, 19, -24], [30, 18, -24], [29, 17, -24], [28, 16, -24], [27, 15, -24], [26, 14, -24], [25, 13, -24], [24, 12, -24], [23, 12, -24], [22, 13, -24], [21, 13, -24], [20, 14, -24], [19, 14, -24], [18, 15, -24], [17, 15, -24], [16, 15, -24], [15, 16, -24]]},
    {'t': 179.3, 'kind': 'summary', 'floor': 'B2', 'reached': True, 'final_pos': [0.777, 0.823, -1.125], 'final_level': 'B2', 'max_jump': 0.0313, 'route': 'ok', 'route_k': [12, -24]},
    {'t': 179.3, 'kind': 'verdict', 'steps': {'descended level by level to the target floor': {'ok': True, 't': None, 'detail': 'L1 -> ground -> B1 -> B2'}, 'slab dropped on the planned route on the target floor': {'ok': True, 't': 173.6, 'detail': 'slab at [1.125, 0.975] on B2'}, 'Scout stopped short of the slab': {'ok': True, 't': 175.0, 'detail': 'state arrived'}, "slab mapped from the Scout's own measurements": {'ok': True, 't': 173.7, 'detail': "5 occupied cell(s) in the slab's footprint (lidar, refused)"}, 're-planned route avoids the slab': {'ok': True, 't': 173.7, 'detail': '11/11 planned paths after the shift avoid it'}, 'Scout reached the casualty on the target floor': {'ok': True, 't': 179.3, 'detail': 'at [0.777, 0.823, -1.125] on B2'}, 'Scout never entered the slab': {'ok': True, 't': None, 'detail': 'never inside it'}, 'no teleport': {'ok': True, 't': None, 'detail': 'max move 0.0313 m per tick'}, 'route over the scouted map from L1 to the target floor': {'ok': True, 't': None, 'detail': 'ok k [12, -24]'}}, 'passed': ['descended level by level to the target floor', 'slab dropped on the planned route on the target floor', 'Scout stopped short of the slab', "slab mapped from the Scout's own measurements", 're-planned route avoids the slab', 'Scout reached the casualty on the target floor', 'Scout never entered the slab', 'no teleport', 'route over the scouted map from L1 to the target floor'], 'failed': []},
]


def shift_then_recheck(records):
    """{"b2", "shift", "mapped", "recheck", "through_after", "reached"} (sim seconds; None where missing)."""
    b2 = next((r["t"] for r in records if r.get("kind") == "level" and r.get("level") == "B2"), None)
    shift = next((r for r in records if r.get("kind") == "shift"), None)
    out = {"b2": b2, "shift": None, "mapped": None, "recheck": None, "through_after": [], "reached": None}
    if shift is None or shift.get("level") != "B2":
        return out
    out["shift"] = shift["t"]
    core = {tuple(c) for c in shift.get("core", [])}
    mapped = next((r for r in records if r.get("kind") == "mapped" and r["t"] >= shift["t"]
                   and set(r.get("sources", [])) and set(r["sources"]) <= MEASURED), None)
    out["mapped"] = mapped and mapped["t"]
    for r in records:
        if r.get("kind") != "plan" or r["t"] <= shift["t"] or r.get("status") != "ok":
            continue
        misses = not core & {tuple(c[:2]) for c in r.get("cells", [])}
        if out["recheck"] is None and misses:
            out["recheck"] = r["t"]
        elif out["recheck"] is not None and not misses:
            out["through_after"].append(r["t"])
    summary = next((r for r in records if r.get("kind") == "summary"), {})
    if summary.get("reached") is True and summary.get("final_level") == "B2":
        out["reached"] = summary["t"]
    return out


def check(records):
    e = shift_then_recheck(records)
    assert e["b2"] is not None and e["shift"] is not None, f"no slab shift on B2: {e}"
    assert e["b2"] <= e["shift"], e
    assert e["recheck"] is not None and e["recheck"] > e["shift"], f"no recheck after the shift: {e}"
    assert e["mapped"] is not None and e["mapped"] <= e["recheck"], f"recheck without measured evidence: {e}"
    assert e["through_after"] == [], f"a later route goes through the slab: {e}"
    assert e["reached"] is not None and e["reached"] >= e["recheck"], e
    return e


def test_real_b2_log_has_a_shift_then_a_recheck():
    e = check(REAL_B2)
    assert e == {"b2": 155.3, "shift": 173.6, "mapped": 173.7, "recheck": 173.7, "through_after": [], "reached": 179.3}


def test_full_real_b2_log():
    env = os.environ.get("B2_LOG")
    found = [pathlib.Path(env)] if env else sorted((ROOT / "runs").glob("b2-*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not found:
        pytest.skip("no full B2 log: set B2_LOG or run python tools/run_b2.py")
    records = [json.loads(line) for line in found[-1].read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"{found[-1].name}: {check(records)}")


def _broken(change):
    recs = json.loads(json.dumps(REAL_B2))
    change(recs)
    return recs


def _drop(kind):
    return lambda recs: recs.remove(next(r for r in recs if r["kind"] == kind))


def _plans_after_shift(recs):
    t = next(r for r in recs if r["kind"] == "shift")["t"]
    return [r for r in recs if r["kind"] == "plan" and r["t"] > t and r["status"] == "ok"]


def _all_through(recs):
    core = next(r for r in recs if r["kind"] == "shift")["core"]
    for p in _plans_after_shift(recs):
        p["cells"].append([*core[0], -24])


def _later_through(recs):
    core = next(r for r in recs if r["kind"] == "shift")["core"]
    _plans_after_shift(recs)[-1]["cells"].append([*core[0], -24])


def _shift_elsewhere(recs):
    next(r for r in recs if r["kind"] == "shift")["level"] = "B1"


def _truth_map(recs):
    next(r for r in recs if r["kind"] == "mapped")["sources"] = ["truth"]


def _not_reached(recs):
    s = next(r for r in recs if r["kind"] == "summary")
    s["reached"] = False


@pytest.mark.parametrize("change", [
    _drop("shift"),        # no shift at all
    _shift_elsewhere,      # the shift is not on B2
    _all_through,          # no route after the shift misses the slab: no recheck
    _later_through,        # the recheck is found, but a later route goes back through the slab
    _drop("mapped"),       # recheck with no measured evidence
    _truth_map,            # "mapped" from sim truth is not evidence
    _not_reached,          # never reached c2 after the recheck
])
def test_broken_logs_fail(change):
    with pytest.raises(AssertionError):
        check(_broken(change))
