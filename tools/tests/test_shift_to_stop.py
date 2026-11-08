"""SHIFT-TO-STOP: a slab shift on a driven B2 route must make the Scout stop.

tools/run_b2.evaluate already treats a re-plan inside STOP_WINDOW as enough for
"Scout stopped short of the slab". This test is stricter: after the shift the
Scout has to enter a real halt (pose state blocked, idle or stop, or a stop /
stop_and_recheck record) within STOP_WINDOW. A waypoint "arrived" sample is not
a halt — those show up while the Scout is still driving the next hop.

On today's run_b2 the slab is mapped and a new route is chosen in 0.1 s, and
the next 1 Hz pose is still moving. The real-run check is a strict xfail until
drop_slab (or a later stop_and_recheck) actually stops the Scout.
"""

import json
import os

import pytest

from tools.run_b2 import STOP_WINDOW

STOP_STATES = frozenset({"blocked", "idle", "stop"})
STOP_KINDS = frozenset({"stop", "stop_and_recheck"})

real = pytest.mark.skipif(os.environ.get("RUN_B2_REAL") != "1",
                          reason="real B2 run, ~20 s: set RUN_B2_REAL=1")


def _halted(row):
    """True when this record is a real halt, not a waypoint arrival or a re-plan."""
    if row.get("kind") in STOP_KINDS:
        return True
    if row.get("kind") == "pose" and row.get("state") in STOP_STATES:
        return True
    state = row.get("state") or row.get("status")
    return row.get("kind") in ("pose", *STOP_KINDS) and isinstance(state, str) and state.startswith("stop")


def assert_shift_causes_stop(records, window=STOP_WINDOW):
    """The Scout was moving on a planned route, then halted within `window` of the shift."""
    shifts = [r for r in records if r.get("kind") == "shift"]
    assert len(shifts) == 1, f"expected one slab shift, got {len(shifts)}"
    shift = shifts[0]
    prior = [r for r in records if r.get("t", -1) <= shift["t"]]
    assert any(r.get("kind") == "pose" and r.get("state") == "moving" for r in prior), (
        "shift is not on a Scout that was moving")
    assert any(r.get("kind") == "plan" and r.get("status") == "ok" for r in prior), (
        "shift is not on a planned route")
    halt = next((r for r in records
                 if r.get("t", -1) >= shift["t"] and r["t"] <= shift["t"] + window and _halted(r)), None)
    assert halt is not None, (
        f"Scout kept moving after the shift at t={shift['t']} "
        f"(no blocked/idle/stop within {window} s)")
    return halt


def _driving(**extra):
    rows = [
        {"t": 10.0, "kind": "pose", "state": "moving", "pos": [1.50, 1.00, -1.125], "level": "B2"},
        {"t": 10.4, "kind": "plan", "status": "ok", "why": "route", "target": [1.23, 0.97, -1.2]},
        {"t": 10.5, "kind": "shift", "level": "B2", "xy": [1.125, 0.975]},
    ]
    rows.extend(extra.get("after", []))
    return rows


def test_blocked_pose_after_shift_counts_as_stop():
    halt = assert_shift_causes_stop(_driving(after=[
        {"t": 10.6, "kind": "pose", "state": "blocked", "pos": [1.48, 1.00, -1.125], "level": "B2"},
    ]))
    assert halt["state"] == "blocked" and halt["t"] == pytest.approx(10.6)


def test_idle_pose_and_stop_records_count_as_stop():
    idle = assert_shift_causes_stop(_driving(after=[
        {"t": 11.0, "kind": "pose", "state": "idle", "pos": [1.48, 1.00, -1.125], "level": "B2"},
    ]))
    assert idle["state"] == "idle"
    rec = assert_shift_causes_stop(_driving(after=[
        {"t": 10.7, "kind": "stop_and_recheck"},
    ]))
    assert rec["kind"] == "stop_and_recheck"


def test_replan_while_still_moving_is_not_a_stop():
    """Today's run_b2 shape: map + new route in 0.1 s, next pose still moving."""
    rows = _driving(after=[
        {"t": 10.6, "kind": "mapped", "cells": 4, "sources": ["lidar"]},
        {"t": 10.6, "kind": "plan", "status": "ok", "why": "route", "target": [1.48, 1.18, -1.2]},
        {"t": 11.0, "kind": "pose", "state": "moving", "pos": [1.46, 1.16, -1.125], "level": "B2"},
        {"t": 12.0, "kind": "pose", "state": "arrived", "pos": [1.57, 1.03, -1.125], "level": "B2"},
        {"t": 13.0, "kind": "pose", "state": "moving", "pos": [1.44, 0.84, -1.125], "level": "B2"},
    ])
    with pytest.raises(AssertionError, match="kept moving"):
        assert_shift_causes_stop(rows)


def test_arrived_waypoint_is_not_a_stop():
    rows = _driving(after=[
        {"t": 11.0, "kind": "pose", "state": "arrived", "pos": [1.57, 1.03, -1.125], "level": "B2"},
        {"t": 12.0, "kind": "pose", "state": "moving", "pos": [1.44, 0.84, -1.125], "level": "B2"},
    ])
    with pytest.raises(AssertionError, match="kept moving"):
        assert_shift_causes_stop(rows)


def test_halt_after_the_stop_window_does_not_count():
    rows = _driving(after=[
        {"t": 10.5 + STOP_WINDOW + 0.1, "kind": "pose", "state": "blocked",
         "pos": [1.40, 1.00, -1.125], "level": "B2"},
    ])
    with pytest.raises(AssertionError, match="kept moving"):
        assert_shift_causes_stop(rows)


def test_missing_or_extra_shift_is_rejected():
    with pytest.raises(AssertionError, match="one slab shift"):
        assert_shift_causes_stop([
            {"t": 10.0, "kind": "pose", "state": "moving"},
            {"t": 10.4, "kind": "plan", "status": "ok"},
        ])
    with pytest.raises(AssertionError, match="one slab shift"):
        assert_shift_causes_stop(_driving(after=[
            {"t": 12.0, "kind": "shift", "level": "B2"},
            {"t": 12.1, "kind": "pose", "state": "blocked"},
        ]))


@real
@pytest.mark.xfail(strict=True, reason="run_b2 maps the slab and re-plans in 0.1 s; "
                   "the next pose is still moving — no blocked/idle/stop "
                   "(or stop_and_recheck) after drop_slab")
def test_real_b2_slab_shift_stops_the_scout(tmp_path):
    pytest.importorskip("mujoco")
    from tools.run_b2 import run

    _verdict, path = run(seed=0, out_dir=tmp_path, floor="B2")
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    shift = next(r for r in records if r["kind"] == "shift")
    assert shift["level"] == "B2"
    halt = assert_shift_causes_stop(records)
    assert halt["t"] >= shift["t"]
