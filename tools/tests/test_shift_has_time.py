"""SHIFT-HAS-TIME: real slab-shift timestamps follow the simulation chronology.

Interpret `t` as numeric, finite, nonnegative seconds since sim start, on the
runner's 0.1 s tick grid and between surrounding records/poses within the run.
Exercise real B2/B3 slab-shift logs, not a synthetic run. The runner emits
`kind=shift`, not hub `world/change`: bus events, wall-clock/UTC accuracy,
sub-tick physics timing and multiple-shift coverage are NOT established here.
"""

import json
import math
from itertools import pairwise

import pytest

from tools import run_b2


def assert_shift_timestamps_follow_sim_time(records):
    assert records
    for record in records:
        t = record.get("t")
        assert type(t) in (int, float) and math.isfinite(t) and t >= 0, record
    assert records[0]["t"] == 0.0
    assert all(a["t"] <= b["t"] for a, b in pairwise(records))
    summary = next(r for r in records if r["kind"] == "summary")
    assert 0 < summary["t"] <= 500.0  # this test's sim-time deadline, not epoch time
    shifts = [(i, r) for i, r in enumerate(records) if r["kind"] == "shift"]
    assert shifts, "no real shift was exercised"
    for index, shift in shifts:
        t = shift["t"]
        assert 0 < t < summary["t"], shift
        assert math.isclose(t / 0.1, round(t / 0.1), rel_tol=0, abs_tol=1e-7), shift
        assert 0 < index < len(records) - 1
        assert records[index - 1]["t"] <= t <= records[index + 1]["t"], shift
        before = next((r for r in reversed(records[:index]) if r["kind"] == "pose"), None)
        after = next((r for r in records[index + 1:] if r["kind"] == "pose"), None)
        assert before is not None and after is not None, shift
        # Poses are ~1 Hz: allow one extra 0.1 s tick for floating-point
        # scheduling at the 1 s boundary, not arbitrarily stale timestamps.
        assert 0 <= t - before["t"] <= 1.1 + 1e-9, (before, shift)
        assert 0 <= after["t"] - t <= 1.1 + 1e-9, (shift, after)
        level = next(r for r in reversed(records[:index]) if r["kind"] == "level")
        assert level["t"] <= t and level["level"] == shift["level"], (level, shift)


@pytest.mark.parametrize("floor", ["B2", "B3"])
def test_real_slab_shift_has_valid_sim_timestamp(tmp_path, floor):
    verdict, path = run_b2.run(seed=0, max_t=500.0, out_dir=tmp_path, floor=floor)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert verdict["failed"] == [], verdict
    assert_shift_timestamps_follow_sim_time(records)
    assert all(r["level"] == floor for r in records if r["kind"] == "shift")
