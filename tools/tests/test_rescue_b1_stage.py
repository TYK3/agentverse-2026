"""B1-SLAB-EVENT: run_rescue --b1 logs the B1 slab shift, the stop and the fresh recheck."""

from tools import run_rescue as R


def records(shift=True, stopped=True):
    rows = [{"t": 0.0, "kind": "pose", "cell": [0, 0, 6], "state": "moving"},
            {"t": 0.1, "kind": "pose", "cell": [0, 0, 6], "state": "moving"},
            {"t": 0.2, "kind": "level", "level": "L1"},
            {"t": 5.0, "kind": "plan", "cells": [[1, 1, 0]], "status": "ok"},   # before the shift: not copied
            {"t": 9.0, "kind": "level", "level": "ground"},
            {"t": 20.0, "kind": "level", "level": "B1"},
            {"t": 20.5, "kind": "pose", "cell": [3, 3, -12], "state": "moving"}]
    if shift:
        rows += [{"t": 30.0, "kind": "shift", "xy": [1.1, 0.6], "level": "B1", "core": [[22, 12]]},
                 {"t": 30.1, "kind": "mapped", "cells": 6, "sources": ["lidar"]},
                 {"t": 30.2, "kind": "plan", "cells": [[5, 5, -12]], "status": "ok"}]
    rows += [{"t": 40.0, "kind": "summary", "floor": "B1", "reached": True, "final_pos": [0.76, 1.56, -0.52],
              "max_jump": 0.03, "route": "ok", "route_k": [12, -12]}]
    steps = {n: {"ok": shift and (stopped or n != "Scout stopped short of the slab"), "detail": n}
             for n in R.B1_SHIFT_STEPS}
    rows.append({"t": 40.0, "kind": "verdict", "steps": steps})
    return rows


def test_shift_stop_and_recheck_are_logged_and_pass():
    notes, stage, ok, _ = R.b1_stage(records())
    topics = [t for t, _ in notes]
    for kind in ("shift", "mapped", "level", "summary", "verdict"):
        assert f"_b1/{kind}" in topics
    plans = [d for t, d in notes if t == "_b1/plan"]
    assert [p["t"] for p in plans] == [30.2], "only plans after the shift are copied"
    assert topics.count("_probe/b1_cell") == 2, "one cell probe per new cell"
    assert ok
    assert stage["stage"] == "b1" and stage["reached"] is True
    assert stage["levels"] == ["L1", "ground", "B1"] and stage["shift_t"] == 30.0
    assert stage["final_pos"] == [0.76, 1.56, -0.52]
    assert "off the hub" in stage["permit"]


def test_no_shift_fails_the_step():
    notes, stage, ok, detail = R.b1_stage(records(shift=False))
    assert not ok and stage["shift_t"] is None
    assert not [t for t, _ in notes if t == "_b1/shift"]
    assert "slab dropped" in detail


def test_driving_on_fails_the_step_and_names_why():
    _, _, ok, detail = R.b1_stage(records(stopped=False))
    assert not ok and "Scout stopped short of the slab" in detail
