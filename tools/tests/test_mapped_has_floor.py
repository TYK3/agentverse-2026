"""MAPPED-HAS-FLOOR: every mapped record in a real run log names its floor.

A mapped record is the post-shift slab measurement (kind "mapped"). Each one
must name the floor the slab landed on (`floor` or `level` in L1, ground, B1,
B2 or B3) and that name must match the latest level event, the preceding
shift's level, and the summary's target floor when those are present.

Today's mapped records carry t, cells and sources only. console/tests/fixtures/b2-seed0.jsonl
is a saved real B2 seed-0 log: one mapped line at t=173.7 after the B2 shift,
with no floor field. The real-log check is a strict xfail until the runner
writes the floor on each mapped record. This file does not edit the writer or
the schema.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REAL_B2 = ROOT / "console/tests/fixtures/b2-seed0.jsonl"

FLOORS = ("L1", "ground", "B1", "B2", "B3")


def mapped_floor(record):
    """Named floor on a mapped record, or None if missing or not a floor name."""
    name = record.get("floor", record.get("level"))
    if isinstance(name, str) and name in FLOORS:
        return name
    return None


def assert_mapped_have_floor(records):
    """Every mapped record names a floor that agrees with the run so far."""
    mapped = [row for row in records if row.get("kind") == "mapped"]
    assert mapped, "real run log has no mapped records"
    current = None
    shift_floor = None
    for row in records:
        kind = row.get("kind")
        if kind == "level" and row.get("level") in FLOORS:
            current = row["level"]
        elif kind == "shift":
            name = row.get("level", row.get("floor"))
            if name in FLOORS:
                shift_floor = name
        elif kind == "mapped":
            floor = mapped_floor(row)
            assert floor is not None, f"mapped at t={row.get('t')} names no floor"
            if current in FLOORS:
                assert floor == current, (
                    f"mapped at t={row.get('t')} names {floor}, "
                    f"but the last level event is {current}"
                )
            if shift_floor in FLOORS:
                assert floor == shift_floor, (
                    f"mapped at t={row.get('t')} names {floor}, "
                    f"but the shift is on {shift_floor}"
                )
    summary = next((row for row in records if row.get("kind") == "summary"), None)
    target = summary.get("floor") if summary else None
    if target in FLOORS:
        for row in mapped:
            floor = mapped_floor(row)
            assert floor == target, (
                f"mapped at t={row.get('t')} names {floor}, "
                f"but the summary target is {target}"
            )
    return mapped


def _log(*mapped, levels=None, shift=None, summary=None):
    rows = []
    for t, name in (levels or ((0.0, "L1"), (21.6, "ground"), (80.1, "B1"), (155.3, "B2"))):
        rows.append({"t": t, "kind": "level", "level": name})
    if shift is not False:
        rows.append(shift or {"t": 173.6, "kind": "shift", "level": "B2"})
    rows.extend(mapped)
    if summary is not False:
        rows.append(summary or {"t": 179.3, "kind": "summary", "floor": "B2"})
    rows.sort(key=lambda row: row["t"])
    return rows


def test_mapped_records_that_name_matching_floors_pass():
    mapped = assert_mapped_have_floor(_log(
        {"t": 173.7, "kind": "mapped", "cells": 5, "sources": ["lidar"], "floor": "B2"},
    ))
    assert [mapped_floor(row) for row in mapped] == ["B2"]
    mapped = assert_mapped_have_floor(_log(
        {"t": 173.7, "kind": "mapped", "cells": 5, "sources": ["lidar"], "level": "B2"},
    ))
    assert mapped_floor(mapped[0]) == "B2"


@pytest.mark.parametrize("mutation", [
    "missing", "empty", "numeric", "unknown", "ramp", "wrong_floor",
    "wrong_shift", "wrong_summary", "no_mapped",
])
def test_incorrect_mapped_floor_is_rejected(mutation):
    rows = _log({"t": 173.7, "kind": "mapped", "cells": 5, "sources": ["lidar"], "floor": "B2"})
    message = "names no floor"
    if mutation == "no_mapped":
        rows = [row for row in rows if row["kind"] != "mapped"]
        message = "no mapped records"
    elif mutation == "wrong_shift":
        shift = next(row for row in rows if row["kind"] == "shift")
        shift["level"] = "B1"
        message = "shift is on"
    elif mutation == "wrong_summary":
        summary = next(row for row in rows if row["kind"] == "summary")
        summary["floor"] = "B1"
        message = "summary target"
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
            message = "last level event"
    with pytest.raises(AssertionError, match=message):
        assert_mapped_have_floor(rows)


def test_saved_b2_seed0_log_has_a_mapped_record_without_a_floor():
    records = [json.loads(line) for line in REAL_B2.read_text().splitlines() if line.strip()]
    mapped = [row for row in records if row["kind"] == "mapped"]
    assert len(mapped) == 1
    assert mapped[0]["t"] == pytest.approx(173.7)
    assert mapped[0]["cells"] > 0
    assert "lidar" in mapped[0]["sources"]
    assert mapped_floor(mapped[0]) is None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "tools/run_b2.py writes mapped records with t, cells and sources only; "
        "a real B2 seed-0 log has no floor or level on its mapped line at "
        "t=173.7. Fix = log the floor the slab was measured on."
    ),
)
def test_every_mapped_record_in_a_real_run_log_names_its_floor():
    records = [json.loads(line) for line in REAL_B2.read_text().splitlines() if line.strip()]
    assert_mapped_have_floor(records)
