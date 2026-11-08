"""RECHECK-LOG: a run log carries the evidence for the Scout's recheck after a slab shift (ref b3).

For a tools/run_b2.py log with a slab shift, the log itself must show:
- a `mapped` record after the shift, within the runner's STOP_WINDOW, with occupied cells in the slab's
  footprint, from the Scout's own measurements only (`lidar`, `refused`), never from sim truth;
- that every planned route after the shift misses the slab's core, and the first one after the slab was
  mapped too (the recheck);
- that the verdict line agrees with the records: tools.run_b2.evaluate() on the logged records gives
  the same steps, so the log is self-consistent, not just a claim.
`recheck_evidence()` collects that; the tests check it on a real B3 log and on broken logs.

Real log: REAL_B3_AFTER_SHIFT (seed 0 on main, 9/9: the level, summary and verdict records and every
record from the shift at 225.8 s on), and, when available, a full log from $B3_LOG or the newest
runs/b3-*.jsonl (it skips otherwise; CI has neither).
"""

import json
import os
import pathlib

import pytest

from tools.run_b2 import STOP_WINDOW, evaluate

ROOT = pathlib.Path(__file__).resolve().parents[2]
MEASURED = {"lidar", "refused"}

REAL_B3_AFTER_SHIFT = [
    {'t': 0.0, 'kind': 'level', 'level': 'L1'},
    {'t': 21.6, 'kind': 'level', 'level': 'ground'},
    {'t': 65.9, 'kind': 'level', 'level': 'B1'},
    {'t': 142.9, 'kind': 'level', 'level': 'B2'},
    {'t': 217.0, 'kind': 'level', 'level': 'B3'},
    {'t': 225.8, 'kind': 'plan', 'status': 'ok', 'why': 'route', 'target': [0.68, 1.43, -1.8], 'cells': [[13, 12, -36], [13, 13, -36], [13, 14, -36], [13, 15, -36], [13, 16, -36], [13, 17, -36], [13, 18, -36], [13, 19, -36], [13, 20, -36], [13, 21, -36], [13, 22, -36], [13, 23, -36], [13, 24, -36], [13, 25, -36], [13, 26, -36], [13, 27, -36], [13, 28, -36], [14, 29, -36], [14, 30, -36], [15, 31, -36], [15, 32, -36]]},
    {'t': 225.8, 'kind': 'shift', 'xy': [0.675, 0.925], 'level': 'B3', 'core': [[11, 16], [11, 17], [11, 18], [11, 19], [11, 20], [12, 16], [12, 17], [12, 18], [12, 19], [12, 20], [13, 16], [13, 17], [13, 18], [13, 19], [13, 20], [14, 16], [14, 17], [14, 18], [14, 19], [14, 20], [15, 16], [15, 17], [15, 18], [15, 19], [15, 20]], 'scout': [0.678, 0.622, -1.725]},
    {'t': 226.0, 'kind': 'mapped', 'cells': 4, 'sources': ['lidar', 'refused']},
    {'t': 226.0, 'kind': 'pose', 'pos': [0.678, 0.652, -1.725], 'state': 'blocked', 'level': 'B3', 'cell': [13, 13, -36]},
    {'t': 226.0, 'kind': 'plan', 'status': 'ok', 'why': 'route', 'target': [0.78, 0.57, -1.8], 'cells': [[13, 13, -36], [14, 12, -36], [15, 11, -36], [16, 12, -36], [17, 13, -36], [17, 14, -36], [18, 15, -36], [18, 16, -36], [18, 17, -36], [18, 18, -36], [18, 19, -36], [18, 20, -36], [18, 21, -36], [18, 22, -36], [18, 23, -36], [18, 24, -36], [18, 25, -36], [18, 26, -36], [17, 27, -36], [17, 28, -36], [16, 29, -36], [16, 30, -36], [16, 31, -36], [15, 32, -36]]},
    {'t': 226.5, 'kind': 'plan', 'status': 'ok', 'why': 'route', 'target': [0.82, 0.62, -1.8], 'cells': [[15, 11, -36], [16, 12, -36], [17, 12, -36], [18, 13, -36], [19, 14, -36], [19, 15, -36], [20, 16, -36], [20, 17, -36], [20, 18, -36], [20, 19, -36], [20, 20, -36], [20, 21, -36], [19, 22, -36], [18, 23, -36], [17, 24, -36], [16, 25, -36], [15, 26, -36], [15, 27, -36], [15, 28, -36], [15, 29, -36], [15, 30, -36], [15, 31, -36], [15, 32, -36]]},
    {'t': 226.8, 'kind': 'plan', 'status': 'ok', 'why': 'route', 'target': [0.88, 0.62, -1.8], 'cells': [[16, 12, -36], [17, 12, -36], [18, 13, -36], [19, 14, -36], [19, 15, -36], [20, 16, -36], [20, 17, -36], [20, 18, -36], [20, 19, -36], [20, 20, -36], [20, 21, -36], [20, 22, -36], [19, 23, -36], [18, 24, -36], [17, 25, -36], [16, 26, -36], [15, 27, -36], [15, 28, -36], [15, 29, -36], [15, 30, -36], [15, 31, -36], [15, 32, -36]]},
    {'t': 227.0, 'kind': 'pose', 'pos': [0.875, 0.625, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [17, 12, -36]},
    {'t': 227.1, 'kind': 'plan', 'status': 'ok', 'why': 'route', 'target': [1.02, 0.78, -1.8], 'cells': [[17, 12, -36], [18, 13, -36], [19, 14, -36], [20, 15, -36], [20, 16, -36], [20, 17, -36], [20, 18, -36], [20, 19, -36], [20, 20, -36], [20, 21, -36], [20, 22, -36], [19, 23, -36], [19, 24, -36], [18, 25, -36], [18, 26, -36], [17, 27, -36], [17, 28, -36], [16, 29, -36], [16, 30, -36], [16, 31, -36], [15, 32, -36]]},
    {'t': 227.9, 'kind': 'plan', 'status': 'ok', 'why': 'route', 'target': [1.02, 1.32, -1.8], 'cells': [[20, 15, -36], [20, 16, -36], [20, 17, -36], [20, 18, -36], [20, 19, -36], [20, 20, -36], [20, 21, -36], [20, 22, -36], [20, 23, -36], [20, 24, -36], [20, 25, -36], [20, 26, -36], [19, 27, -36], [18, 28, -36], [17, 29, -36], [16, 30, -36], [16, 31, -36], [15, 32, -36]]},
    {'t': 228.0, 'kind': 'pose', 'pos': [1.024, 0.803, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [20, 16, -36]},
    {'t': 229.0, 'kind': 'pose', 'pos': [1.024, 1.103, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [20, 22, -36]},
    {'t': 229.8, 'kind': 'plan', 'status': 'ok', 'why': 'route', 'target': [0.82, 1.52, -1.8], 'cells': [[20, 26, -36], [19, 27, -36], [18, 28, -36], [17, 29, -36], [16, 30, -36], [16, 31, -36], [15, 32, -36]]},
    {'t': 230.0, 'kind': 'pose', 'pos': [0.984, 1.357, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [19, 27, -36]},
    {'t': 230.9, 'kind': 'summary', 'floor': 'B3', 'reached': True, 'final_pos': [0.825, 1.525, -1.725], 'final_level': 'B3', 'max_jump': 0.0313, 'route': 'ok', 'route_k': [12, -36]},
    {'t': 230.9, 'kind': 'verdict', 'steps': {'descended level by level to the target floor': {'ok': True, 't': None, 'detail': 'L1 -> ground -> B1 -> B2 -> B3'}, 'slab dropped on the planned route on the target floor': {'ok': True, 't': 225.8, 'detail': 'slab at [0.675, 0.925] on B3'}, 'Scout stopped short of the slab': {'ok': True, 't': 226.0, 'detail': 'state blocked'}, "slab mapped from the Scout's own measurements": {'ok': True, 't': 226.0, 'detail': "4 occupied cell(s) in the slab's footprint (lidar, refused)"}, 're-planned route avoids the slab': {'ok': True, 't': 226.0, 'detail': '6/6 planned paths after the shift avoid it'}, 'Scout reached the casualty on the target floor': {'ok': True, 't': 230.9, 'detail': 'at [0.825, 1.525, -1.725] on B3'}, 'Scout never entered the slab': {'ok': True, 't': None, 'detail': 'never inside it'}, 'no teleport': {'ok': True, 't': None, 'detail': 'max move 0.0313 m per tick'}, 'route over the scouted map from L1 to the target floor': {'ok': True, 't': None, 'detail': 'ok k [12, -36]'}}, 'passed': ['descended level by level to the target floor', 'slab dropped on the planned route on the target floor', 'Scout stopped short of the slab', "slab mapped from the Scout's own measurements", 're-planned route avoids the slab', 'Scout reached the casualty on the target floor', 'Scout never entered the slab', 'no teleport', 'route over the scouted map from L1 to the target floor'], 'failed': []},
]


def recheck_evidence(records):
    """What the log shows about the recheck: shift, mapped, routes after the shift, verdict agreement."""
    shift = next((r for r in records if r.get("kind") == "shift"), None)
    if shift is None:
        return {"shift": None}
    core = {tuple(c) for c in shift.get("core", [])}
    after = [r for r in records if r["t"] >= shift["t"]]
    mapped = next((r for r in after if r.get("kind") == "mapped"), None)
    routes = [r for r in after if r.get("kind") == "plan" and r.get("cells") and r["t"] > shift["t"]]
    through = [r["t"] for r in routes if core & {tuple(c[:2]) for c in r["cells"]}]
    first_after_map = next((r for r in routes if mapped and r["t"] >= mapped["t"]), None)
    logged = next((r for r in records if r.get("kind") == "verdict"), None)
    body = [r for r in records if r.get("kind") != "verdict"]
    return {
        "shift": shift["t"],
        "mapped": mapped and mapped["t"],
        "mapped_cells": mapped and mapped.get("cells"),
        "mapped_sources": sorted(mapped.get("sources", [])) if mapped else None,
        "routes_after_shift": len(routes),
        "routes_through_slab": through,
        "recheck": first_after_map and first_after_map["t"],
        "verdict_agrees": logged is not None and logged.get("steps") == evaluate(body)["steps"],
    }


def check(records):
    e = recheck_evidence(records)
    assert e["shift"] is not None, "no slab shift in this log"
    assert e["mapped"] is not None, "no mapped record after the shift"
    assert e["mapped"] - e["shift"] <= STOP_WINDOW, e
    assert e["mapped_cells"] > 0, e
    assert e["mapped_sources"] and set(e["mapped_sources"]) <= MEASURED, f"not from the Scout's own scan: {e}"
    assert e["routes_after_shift"] > 0 and e["routes_through_slab"] == [], e
    assert e["recheck"] is not None, e
    assert e["verdict_agrees"], "the logged verdict does not match its own records"
    return e


def test_real_b3_log_carries_the_recheck_evidence():
    e = check(REAL_B3_AFTER_SHIFT)
    assert e == {"shift": 225.8, "mapped": 226.0, "mapped_cells": 4, "mapped_sources": ["lidar", "refused"],
                 "routes_after_shift": 6, "routes_through_slab": [], "recheck": 226.0, "verdict_agrees": True}


def test_full_real_b3_log_carries_the_recheck_evidence():
    env = os.environ.get("B3_LOG")
    found = [pathlib.Path(env)] if env else sorted((ROOT / "runs").glob("b3-*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not found:
        pytest.skip("no full B3 log: set B3_LOG or run python tools/run_b2.py --floor B3")
    records = [json.loads(line) for line in found[-1].read_text(encoding="utf-8").splitlines() if line.strip()]
    e = check(records)
    print(f"{found[-1].name}: {e}")


def _broken(change):
    recs = json.loads(json.dumps(REAL_B3_AFTER_SHIFT))
    change(recs)
    return recs


def _set_sources(recs, sources):
    next(r for r in recs if r["kind"] == "mapped")["sources"] = sources


def _route_through(recs):
    shift = next(r for r in recs if r["kind"] == "shift")
    plan = next(r for r in recs if r["kind"] == "plan" and r["t"] > shift["t"])
    plan["cells"].append([*shift["core"][0], -36])


def _late_map(recs):
    next(r for r in recs if r["kind"] == "mapped")["t"] = 225.8 + STOP_WINDOW + 1.0


def _verdict_lies(recs):
    v = next(r for r in recs if r["kind"] == "verdict")
    v["steps"]["re-planned route avoids the slab"]["detail"] = "7/7 planned paths after the shift avoid it"


@pytest.mark.parametrize("change", [
    lambda r: _set_sources(r, ["truth"]),                                  # mapped from sim truth
    lambda r: _set_sources(r, []),                                         # no source at all
    lambda r: r.remove(next(x for x in r if x["kind"] == "mapped")),       # never mapped
    lambda r: next(x for x in r if x["kind"] == "mapped").update(cells=0),  # mapped nothing
    _route_through,                                                        # a later route through the slab
    _late_map,                                                             # mapped too late
    _verdict_lies,                                                         # verdict not from these records
])
def test_missing_or_false_evidence_fails(change):
    with pytest.raises(AssertionError):
        check(_broken(change))
