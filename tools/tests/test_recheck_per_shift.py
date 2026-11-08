"""RECHECK-PER-SHIFT: every slab shift is followed by its own measured recheck.

A recheck is a "mapped" record written by tools/run_b2.py once the Scout has
occupied cells on that slab from its own sensing (LiDAR hits or a refused
step), not from sim truth. Each shift needs one of those records at or after
its own time and before the next shift: a later map of a second slab must not
stand in for the first, and a map that landed before the shift does not count.

One B2 shift already writes this (mapped 0.1 s later, cells > 0, sources
lidar/refused). The unit checks also cover two shifts so a runner that maps
only the first one cannot pass.
"""

import json
import os

import pytest

real = pytest.mark.skipif(os.environ.get("RUN_B2_REAL") != "1",
                          reason="real B2 run, ~20 s: set RUN_B2_REAL=1")


def _recheck_after(shift, records, end_t):
    """First measured map of the slab that belongs to this shift, or None."""
    return next((r for r in records
                 if r.get("kind") == "mapped"
                 and shift["t"] <= r.get("t", -1) < end_t
                 and r.get("cells", 0) > 0
                 and r.get("sources")), None)


def assert_recheck_per_shift(records):
    """Every shift has its own later mapped record with cells and sources."""
    shifts = [r for r in records if r.get("kind") == "shift"]
    assert shifts, "log has no slab-shift marker"
    missing = []
    paired = []
    for i, shift in enumerate(shifts):
        end_t = shifts[i + 1]["t"] if i + 1 < len(shifts) else float("inf")
        mapped = _recheck_after(shift, records, end_t)
        if mapped is None:
            missing.append(shift["t"])
        else:
            paired.append((shift, mapped))
    assert not missing, f"no measured recheck after shift(s) at t={missing}"
    return paired


def _shift(t, level="B2"):
    return {"t": t, "kind": "shift", "level": level, "xy": [1.125, 0.975]}


def _mapped(t, cells=5, sources=None):
    return {"t": t, "kind": "mapped", "cells": cells,
            "sources": list(sources if sources is not None else ["lidar", "refused"])}


def test_single_shift_with_a_measured_map_passes():
    paired = assert_recheck_per_shift([
        _shift(173.6),
        _mapped(173.7),
    ])
    assert len(paired) == 1
    shift, mapped = paired[0]
    assert mapped["t"] == pytest.approx(173.7) and mapped["cells"] == 5
    assert shift["t"] < mapped["t"]


def test_each_of_two_shifts_needs_its_own_map():
    paired = assert_recheck_per_shift([
        _shift(10.0),
        _mapped(10.1, cells=3, sources=["lidar"]),
        _shift(20.0),
        _mapped(20.2, cells=4, sources=["refused"]),
    ])
    assert [m["t"] for _, m in paired] == [10.1, 20.2]


def test_a_later_map_does_not_cover_an_earlier_shift():
    rows = [
        _shift(10.0),
        _shift(20.0),
        _mapped(20.2),
    ]
    with pytest.raises(AssertionError, match=r"t=\[10.0\]"):
        assert_recheck_per_shift(rows)


def test_a_map_before_the_shift_does_not_count():
    rows = [
        _mapped(10.0),
        _shift(10.5),
    ]
    with pytest.raises(AssertionError, match=r"t=\[10.5\]"):
        assert_recheck_per_shift(rows)


def test_empty_or_unmeasured_map_does_not_count():
    with pytest.raises(AssertionError, match=r"t=\[10.5\]"):
        assert_recheck_per_shift([_shift(10.5), _mapped(10.6, cells=0)])
    with pytest.raises(AssertionError, match=r"t=\[10.5\]"):
        assert_recheck_per_shift([_shift(10.5), _mapped(10.6, sources=[])])


def test_missing_shift_is_rejected():
    with pytest.raises(AssertionError, match="no slab-shift"):
        assert_recheck_per_shift([_mapped(10.6)])


@real
def test_real_b2_shift_has_its_own_measured_recheck(tmp_path):
    pytest.importorskip("mujoco")
    from tools.run_b2 import run

    _verdict, path = run(seed=0, out_dir=tmp_path, floor="B2")
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    paired = assert_recheck_per_shift(records)
    assert len(paired) == 1
    shift, mapped = paired[0]
    assert shift["level"] == "B2"
    assert mapped["cells"] > 0 and mapped["sources"]
    assert mapped["t"] >= shift["t"]
