"""SCAN-AFTER-SHIFT: after the slab shift, a real B2 run scans before it plans again.

A scan in this log is a record of kind "mapped". tools/run_b2.py does not write
sensors/scout or map/cells lines. While the Scout is stopped, and every
SCAN_EVERY frame while it drives, the loop passes the Scout's sensor payload to
GridLevels.add_sensors. When that map then holds occupied cells in the slab
footprint, it appends {"kind": "mapped", "cells": N, "sources": [...]}. "cells"
is the mapped-cell count from the Scout's own LiDAR or a refused step.
CONTRACT.md's map/cells is that map: a world change must trigger a re-scan, and
only measured cells count (permit evidence kind fresh_scan is the same idea).
A pose, a plan, or sim truth is not a scan.

The mapped record must be strictly after the shift (its t greater than the
shift's t) and earlier in the log than the first plan record after the shift,
with t at most tools.run_b2.STOP_WINDOW seconds later. STOP_WINDOW (3.0 sim
seconds) is the runner's own post-shift window: stop or turn away. The runner
stamps the mapped line and the plan that follows it with the same w.t when both
are written before the next tick, so "before the plan" is log order.

ADD-BLOCK-Z does not explain this result. World.add_block clamps an asked z up
to just above ground (z = 0.055), so a B2 inject lands on the ground floor; the
fix is open PR #272 and is not merged. This runner never calls add_block. It
places the slab with drop_slab at floor_z + half-height + 0.002. Seed 0 logs a
mapped record (lidar and refused) between the shift and the next plan.
"""

import json

import pytest

pytest.importorskip("mujoco")

from tools.run_b2 import STOP_WINDOW, run

# The log record that counts as a scan, and the field that holds the mapped-cell count.
SCAN_KIND = "mapped"
SCAN_FIELD = "cells"


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.slow
def test_scout_scans_after_the_slab_shift_and_before_the_next_plan(tmp_path, monkeypatch):
    """Seed 0, GEMINI_MODE=off, live LevelWorld. The run is about 21 s."""
    monkeypatch.setenv("GEMINI_MODE", "off")
    _verdict, path = run(seed=0, out_dir=tmp_path)
    records = _records(path)

    shift_at = [i for i, row in enumerate(records) if row["kind"] == "shift"]
    assert shift_at, "B2 log has no shift record"
    shift_i = shift_at[0]
    shift = records[shift_i]

    plan_at = [i for i, row in enumerate(records) if i > shift_i and row["kind"] == "plan"]
    assert plan_at, "B2 log has no plan record after the shift"
    plan_i = plan_at[0]
    plan = records[plan_i]

    between = [
        records[i] for i in range(shift_i + 1, plan_i) if records[i]["kind"] == SCAN_KIND
    ]
    in_window = [
        scan for scan in between
        if scan["t"] > shift["t"]
        and scan["t"] <= plan["t"]
        and scan["t"] <= shift["t"] + STOP_WINDOW
        and isinstance(scan.get(SCAN_FIELD), int)
        and scan[SCAN_FIELD] > 0
    ]
    assert in_window, (
        f"no {SCAN_KIND} record with {SCAN_FIELD} > 0 strictly after the shift "
        f"at t={shift['t']} (record {shift_i}) and before the plan at t={plan['t']} "
        f"(record {plan_i}), inside STOP_WINDOW={STOP_WINDOW} s; "
        f"mapped records in between: {between}"
    )
