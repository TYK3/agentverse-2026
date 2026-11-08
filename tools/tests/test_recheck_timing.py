"""RECHECK-TIMING: after a slab shift, the Scout's fresh recheck (a re-planned route that avoids the slab)
comes less than RECHECK_LIMIT_S after it stops (ref b3).

Latency is measured on tools/run_b2.py logs, in sim seconds:
- shift:   the `shift` record (the slab lands on the Scout's planned route);
- stop:    the time run_b2's own evaluator gives the "Scout stopped short of the slab" step;
- recheck: the first `plan` after the stop whose status is ok and whose cells miss the slab's core
           (the same avoidance rule as the evaluator's "re-planned route avoids the slab").
Each run's numbers are logged (printed, and as pytest properties). The real runs take minutes, so they
are opt-in like tools/tests/test_run_b2.py: RUN_B2_REAL=1. A real B3 excerpt below runs every time.
"""

import os

import pytest

RECHECK_LIMIT_S = 2.0
STOP_STEP = "Scout stopped short of the slab"

# The real tools/run_b2.py --floor B3 log (seed 0 on main, 9/9 checks) from 225.0 s to 226.6 s: the slab
# lands at 225.8 s, the Scout stops and maps it at 226.0 s, then re-plans around it.
REAL_B3 = [
    {"t":225.0,"kind":"pose","pos":[0.827,0.473,-1.725],"state":"arrived","level":"B3","cell":[16,9,-36]},
    {"t":225.0,"kind":"plan","status":"explore","why":"explore","target":[0.68,0.62,-1.8],"cells":[[16,9,-36],[15,10,-36],[14,11,-36],[13,12,-36],[13,13,-36],[13,14,-36],[12,15,-36]]},
    {"t":225.8,"kind":"plan","status":"ok","why":"route","target":[0.68,1.43,-1.8],"cells":[[13,12,-36],[13,13,-36],[13,14,-36],[13,15,-36],[13,16,-36],[13,17,-36],[13,18,-36],[13,19,-36],[13,20,-36],[13,21,-36],[13,22,-36],[13,23,-36],[13,24,-36],[13,25,-36],[13,26,-36],[13,27,-36],[13,28,-36],[14,29,-36],[14,30,-36],[15,31,-36],[15,32,-36]]},
    {"t":225.8,"kind":"shift","xy":[0.675,0.925],"level":"B3","core":[[11,16],[11,17],[11,18],[11,19],[11,20],[12,16],[12,17],[12,18],[12,19],[12,20],[13,16],[13,17],[13,18],[13,19],[13,20],[14,16],[14,17],[14,18],[14,19],[14,20],[15,16],[15,17],[15,18],[15,19],[15,20]],"scout":[0.678,0.622,-1.725]},
    {"t":226.0,"kind":"mapped","cells":4,"sources":["lidar","refused"]},
    {"t":226.0,"kind":"pose","pos":[0.678,0.652,-1.725],"state":"blocked","level":"B3","cell":[13,13,-36]},
    {"t":226.0,"kind":"plan","status":"ok","why":"route","target":[0.78,0.57,-1.8],"cells":[[13,13,-36],[14,12,-36],[15,11,-36],[16,12,-36],[17,13,-36],[17,14,-36],[18,15,-36],[18,16,-36],[18,17,-36],[18,18,-36],[18,19,-36],[18,20,-36],[18,21,-36],[18,22,-36],[18,23,-36],[18,24,-36],[18,25,-36],[18,26,-36],[17,27,-36],[17,28,-36],[16,29,-36],[16,30,-36],[16,31,-36],[15,32,-36]]},
    {"t":226.5,"kind":"plan","status":"ok","why":"route","target":[0.82,0.62,-1.8],"cells":[[15,11,-36],[16,12,-36],[17,12,-36],[18,13,-36],[19,14,-36],[19,15,-36],[20,16,-36],[20,17,-36],[20,18,-36],[20,19,-36],[20,20,-36],[20,21,-36],[19,22,-36],[18,23,-36],[17,24,-36],[16,25,-36],[15,26,-36],[15,27,-36],[15,28,-36],[15,29,-36],[15,30,-36],[15,31,-36],[15,32,-36]]},
]
REAL_B3_VERDICT = {"steps": {"Scout stopped short of the slab": {"ok": True, "t": 226.0, "detail": "state blocked"}}}


def latency(records, verdict):
    """{"shift", "stop", "recheck", "stop_to_recheck", "shift_to_recheck"} in sim seconds; None where missing."""
    shift = next((r for r in records if r.get("kind") == "shift"), None)
    stop_t = (verdict.get("steps", {}).get(STOP_STEP) or {}).get("t")
    out = {"shift": shift["t"] if shift else None, "stop": stop_t, "recheck": None,
           "stop_to_recheck": None, "shift_to_recheck": None}
    if shift is None or stop_t is None:
        return out
    core = {tuple(c) for c in shift.get("core", [])}
    for r in records:
        if r.get("kind") != "plan" or r["t"] < stop_t or r.get("status") != "ok":
            continue
        if core & {tuple(c[:2]) for c in r.get("cells", [])}:
            continue                                          # still through the slab: not a recheck
        out["recheck"] = r["t"]
        out["stop_to_recheck"] = round(r["t"] - stop_t, 3)
        out["shift_to_recheck"] = round(r["t"] - shift["t"], 3)
        break
    return out


def log(record_property, name, m):
    print(f"recheck timing {name}: shift {m['shift']} s, stop {m['stop']} s, recheck {m['recheck']} s, "
          f"stop->recheck {m['stop_to_recheck']} s, shift->recheck {m['shift_to_recheck']} s")
    for k, v in m.items():
        record_property(f"{name}_{k}", v)


def test_real_b3_excerpt_rechecks_within_the_limit(record_property):
    m = latency(REAL_B3, REAL_B3_VERDICT)
    log(record_property, "b3_seed0_excerpt", m)
    assert (m["shift"], m["stop"], m["recheck"]) == (225.8, 226.0, 226.0)
    assert m["stop_to_recheck"] < RECHECK_LIMIT_S


def _shift(t=10.0):
    return {"t": t, "kind": "shift", "xy": [1.0, 1.0], "level": "B2", "core": [[20, 20], [20, 21]]}


def _plan(t, cells, status="ok"):
    return {"t": t, "kind": "plan", "status": status, "why": "route", "target": [0, 0, 0], "cells": cells}


def _verdict(stop_t):
    return {"steps": {STOP_STEP: {"ok": stop_t is not None, "t": stop_t, "detail": "state blocked"}}}


AROUND = [[19, 19, -24], [18, 20, -24], [18, 21, -24]]
THROUGH = [[19, 19, -24], [20, 20, -24], [20, 21, -24]]


def test_latency_counts_only_an_ok_route_that_misses_the_slab_after_the_stop():
    records = [_shift(10.0),
               _plan(10.1, AROUND),                       # before the stop: not a recheck
               _plan(10.4, THROUGH),                      # after it, but through the slab
               _plan(10.6, AROUND, status="explore"),     # not a route to the goal
               _plan(11.2, AROUND)]                       # the recheck
    m = latency(records, _verdict(10.3))
    assert m == {"shift": 10.0, "stop": 10.3, "recheck": 11.2, "stop_to_recheck": 0.9, "shift_to_recheck": 1.2}


def test_slow_or_missing_recheck_is_caught():
    slow = latency([_shift(10.0), _plan(12.6, AROUND)], _verdict(10.3))
    assert slow["stop_to_recheck"] == 2.3 and not slow["stop_to_recheck"] < RECHECK_LIMIT_S
    assert latency([_shift(10.0), _plan(11.0, THROUGH)], _verdict(10.3))["recheck"] is None
    assert latency([_shift(10.0)], _verdict(None))["stop_to_recheck"] is None      # never stopped
    assert latency([_plan(1.0, AROUND)], _verdict(None))["shift"] is None          # no shift at all


@pytest.mark.skipif(os.environ.get("RUN_B2_REAL") != "1", reason="real runs: set RUN_B2_REAL=1")
@pytest.mark.parametrize("floor", ["B1", "B2", "B3"])
def test_real_runs_recheck_within_the_limit(floor, tmp_path, record_property):
    import json

    from tools.run_b2 import run

    verdict, path = run(seed=0, out_dir=tmp_path, floor=floor)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    m = latency(records, verdict)
    log(record_property, f"{floor.lower()}_seed0", m)
    if m["shift"] is None:
        pytest.skip(f"no slab shift on {floor} in this run (see #214/#222)")
    assert m["stop"] is not None, verdict["steps"]
    assert m["recheck"] is not None, "no re-planned route around the slab after the stop"
    assert m["stop_to_recheck"] < RECHECK_LIMIT_S
