"""SCAN-HAS-FLOOR: every LiDAR scan record in a real run log names its floor.

A scan record is a log line with kind "scan". Each one must name the floor the
Scout was on (`floor` or `level` in L1, ground, B1, B2, B3, or ramp) and that
name must match the latest level event, or be "ramp" between storeys.

tools/run_b2.py does not write scan records. It logs level, pose, plan, mapped
and shift, then a summary and a verdict. LiDAR sweeps update the map in memory;
the only logged measurement is the post-shift "mapped" slab summary, which has
no floor field. console/tests/fixtures/b2-seed0.jsonl is a saved real B2 seed-0
log with the same kinds and no scan lines. The real-log check is a strict xfail
until the runner logs each sweep with its floor. This file does not edit the
writer or the schema.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REAL_B2 = ROOT / "console/tests/fixtures/b2-seed0.jsonl"

FLOORS = ("L1", "ground", "B1", "B2", "B3")
NAMED = FLOORS + ("ramp",)


def scan_floor(record):
    """Named floor on a scan record, or None if missing or not a floor name."""
    name = record.get("floor", record.get("level"))
    if isinstance(name, str) and name in NAMED:
        return name
    return None


def assert_scans_have_floor(records):
    """Every scan record names a floor that agrees with the run so far."""
    scans = [row for row in records if row.get("kind") == "scan"]
    assert scans, (
        "real run log has no LiDAR scan records; tools/run_b2.py writes "
        "level, pose, plan, mapped and shift, then a summary and a verdict"
    )
    current = None
    for row in records:
        kind = row.get("kind")
        if kind == "level":
            current = row.get("level")
        elif kind == "scan":
            floor = scan_floor(row)
            assert floor is not None, f"scan at t={row.get('t')} names no floor"
            if current in FLOORS and floor != "ramp":
                assert floor == current, (
                    f"scan at t={row.get('t')} names {floor}, "
                    f"but the last level event is {current}"
                )
    return scans


def _log(*scans, levels=None):
    rows = []
    for t, name in (levels or ((0.0, "L1"), (21.6, "ground"), (80.1, "B1"), (155.3, "B2"))):
        rows.append({"t": t, "kind": "level", "level": name})
    rows.extend(scans)
    rows.sort(key=lambda row: row["t"])
    return rows


def test_scans_that_name_matching_floors_pass():
    scans = assert_scans_have_floor(_log(
        {"t": 1.0, "kind": "scan", "floor": "L1"},
        {"t": 30.0, "kind": "scan", "level": "ground"},
        {"t": 90.0, "kind": "scan", "floor": "B1"},
        {"t": 160.0, "kind": "scan", "floor": "B2"},
        {"t": 70.0, "kind": "scan", "floor": "ramp"},
    ))
    assert [scan_floor(row) for row in scans] == ["L1", "ground", "ramp", "B1", "B2"]


@pytest.mark.parametrize("mutation", [
    "missing", "empty", "numeric", "unknown", "wrong_floor", "no_scans",
])
def test_incorrect_scan_floor_is_rejected(mutation):
    rows = _log({"t": 160.0, "kind": "scan", "floor": "B2"})
    if mutation == "no_scans":
        rows = [row for row in rows if row["kind"] != "scan"]
        message = "no LiDAR scan records"
    else:
        scan = next(row for row in rows if row["kind"] == "scan")
        if mutation == "missing":
            del scan["floor"]
            message = "names no floor"
        elif mutation == "empty":
            scan["floor"] = ""
            message = "names no floor"
        elif mutation == "numeric":
            scan["floor"] = 2
            message = "names no floor"
        elif mutation == "unknown":
            scan["floor"] = "basement"
            message = "names no floor"
        else:
            scan["floor"] = "B1"
            message = "last level event"
    with pytest.raises(AssertionError, match=message):
        assert_scans_have_floor(rows)


def test_saved_b2_seed0_log_is_a_real_run_without_scan_records():
    records = [json.loads(line) for line in REAL_B2.read_text().splitlines() if line.strip()]
    kinds = {row["kind"] for row in records}
    assert {"level", "pose", "plan", "shift", "mapped", "summary", "verdict"} <= kinds
    assert "scan" not in kinds
    assert any(row["kind"] == "mapped" and "lidar" in row.get("sources", []) for row in records)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "tools/run_b2.py does not write kind=scan records; a real B2 seed-0 "
        "log has level, pose, plan, shift, mapped, summary and verdict only. "
        "Fix = log each LiDAR sweep with its floor."
    ),
)
def test_every_scan_in_a_real_run_log_names_its_floor():
    records = [json.loads(line) for line in REAL_B2.read_text().splitlines() if line.strip()]
    assert_scans_have_floor(records)
