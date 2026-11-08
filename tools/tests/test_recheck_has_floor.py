"""RECHECK-HAS-FLOOR: every measured recheck after a slab shift names its floor.

A recheck is the first "mapped" record at or after a shift and before the next
one, with cells and sources (the Scout measured the slab, as in RECHECK-PER-SHIFT).
Each of those records must name the floor the slab landed on (`floor` or `level`
in L1, ground, B1, B2 or B3), matching that shift's level.

Today's mapped recheck carries t, cells and sources only. The saved real B2
seed-0 log (console/tests/fixtures/b2-seed0.jsonl) has a B2 shift at t=173.6
and a mapped line at t=173.7 with no floor. The real-log check is a strict
xfail until the runner writes the floor on that recheck. This file does not
edit the writer or the schema.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REAL_B2 = ROOT / "console/tests/fixtures/b2-seed0.jsonl"

FLOORS = ("L1", "ground", "B1", "B2", "B3")


def recheck_floor(record):
    """Named floor on a recheck record, or None if missing or not a floor name."""
    name = record.get("floor", record.get("level"))
    if isinstance(name, str) and name in FLOORS:
        return name
    return None


def _recheck_after(shift, records, end_t):
    """First measured map of the slab that belongs to this shift, or None."""
    return next((row for row in records
                 if row.get("kind") == "mapped"
                 and shift["t"] <= row.get("t", -1) < end_t
                 and row.get("cells", 0) > 0
                 and row.get("sources")), None)


def assert_rechecks_have_floor(records):
    """Every shift's measured recheck names the same floor as that shift."""
    shifts = [row for row in records if row.get("kind") == "shift"]
    assert shifts, "log has no slab-shift marker"
    paired = []
    missing = []
    for i, shift in enumerate(shifts):
        end_t = shifts[i + 1]["t"] if i + 1 < len(shifts) else float("inf")
        mapped = _recheck_after(shift, records, end_t)
        if mapped is None:
            missing.append(shift.get("t"))
            continue
        floor = recheck_floor(mapped)
        assert floor is not None, f"recheck at t={mapped.get('t')} names no floor"
        shift_floor = shift.get("level", shift.get("floor"))
        if shift_floor in FLOORS:
            assert floor == shift_floor, (
                f"recheck at t={mapped.get('t')} names {floor}, "
                f"but the shift at t={shift.get('t')} is on {shift_floor}"
            )
        paired.append((shift, mapped))
    assert not missing, f"no measured recheck after shift(s) at t={missing}"
    return paired


def _log(*mapped, shift=None, extra_shifts=None):
    rows = [
        {"t": 0.0, "kind": "level", "level": "L1"},
        {"t": 155.3, "kind": "level", "level": "B2"},
        shift or {"t": 173.6, "kind": "shift", "level": "B2"},
    ]
    rows.extend(mapped)
    rows.extend(extra_shifts or [])
    rows.sort(key=lambda row: row["t"])
    return rows


def test_recheck_that_names_the_shift_floor_passes():
    paired = assert_rechecks_have_floor(_log(
        {"t": 173.7, "kind": "mapped", "cells": 5, "sources": ["lidar", "refused"], "floor": "B2"},
    ))
    assert len(paired) == 1
    assert recheck_floor(paired[0][1]) == "B2"
    paired = assert_rechecks_have_floor(_log(
        {"t": 173.7, "kind": "mapped", "cells": 5, "sources": ["lidar"], "level": "B2"},
    ))
    assert recheck_floor(paired[0][1]) == "B2"


def test_each_of_two_shifts_needs_its_own_floored_recheck():
    rows = _log(
        {"t": 173.7, "kind": "mapped", "cells": 5, "sources": ["lidar"], "floor": "B2"},
        {"t": 200.1, "kind": "mapped", "cells": 4, "sources": ["lidar"], "floor": "B3"},
        extra_shifts=[{"t": 200.0, "kind": "shift", "level": "B3"}],
    )
    paired = assert_rechecks_have_floor(rows)
    assert [recheck_floor(mapped) for _, mapped in paired] == ["B2", "B3"]


@pytest.mark.parametrize("mutation", [
    "missing", "empty", "numeric", "unknown", "ramp", "wrong_floor",
    "no_recheck", "mapped_before_shift",
])
def test_incorrect_recheck_floor_is_rejected(mutation):
    rows = _log({"t": 173.7, "kind": "mapped", "cells": 5, "sources": ["lidar"], "floor": "B2"})
    message = "names no floor"
    if mutation == "no_recheck":
        rows = [row for row in rows if row["kind"] != "mapped"]
        message = "no measured recheck"
    elif mutation == "mapped_before_shift":
        mapped = next(row for row in rows if row["kind"] == "mapped")
        mapped["t"] = 173.5
        message = "no measured recheck"
    else:
        mapped = next(row for row in rows if row["kind"] == "mapped")
        if mutation == "missing":
            del mapped["floor"]
        elif mutation == "empty":
            mapped["floor"] = ""
        elif mutation == "numeric":
            mapped["floor"] = 2
        elif mutation == "unknown":
            mapped["floor"] = "basement"
        elif mutation == "ramp":
            mapped["floor"] = "ramp"
        else:
            mapped["floor"] = "B1"
            message = "shift at t="
    with pytest.raises(AssertionError, match=message):
        assert_rechecks_have_floor(rows)


def test_saved_b2_seed0_log_has_a_measured_recheck_without_a_floor():
    records = [json.loads(line) for line in REAL_B2.read_text().splitlines() if line.strip()]
    shift = next(row for row in records if row["kind"] == "shift")
    assert shift["level"] == "B2"
    mapped = _recheck_after(shift, records, float("inf"))
    assert mapped is not None
    assert mapped["t"] == pytest.approx(173.7)
    assert mapped["cells"] > 0 and mapped["sources"]
    assert recheck_floor(mapped) is None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "the measured recheck after the B2 shift is a mapped record with t, "
        "cells and sources only; a real B2 seed-0 log has no floor on that "
        "line at t=173.7. Fix = log the floor the recheck was measured on."
    ),
)
def test_every_recheck_in_a_real_run_log_names_its_floor():
    records = [json.loads(line) for line in REAL_B2.read_text().splitlines() if line.strip()]
    assert_rechecks_have_floor(records)
