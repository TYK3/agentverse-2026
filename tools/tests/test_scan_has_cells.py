"""SCAN-HAS-CELLS: every LiDAR scan in a real rescue run puts cells into the map, at the Scout's own level.

A scan is one LiDAR sweep that perception.levels.GridLevels maps (_scan: on flat floor, or across a ramp
whose slope it knows; on a ramp it cannot fit yet it only records the trail, so that is no scan). Run once
for real (tools/run_b2.py, seed 0, B2 with its slab shift), each sweep must mark at least one cell from
"lidar", every one of them at the sweep's level k, with free floor among them. Each floor the log reaches
must have been scanned there, and the one scan result the runner logs ("mapped", the slab measured after
the shift) must name its cells. The run logs no scan beats, so passive observers on GridLevels record what
each real sweep marked; nothing in the run or its log is changed.
"""

import copy
import json

import pytest

pytest.importorskip("mujoco")    # a real sim run; CI's tools lane has no MuJoCo (the full job does)

from perception.levels import GridLevels, k_of
from tools import run_b2

FLOOR_Z = {"L1": 0.6, "ground": 0.0, "B1": -0.6, "B2": -1.2, "B3": -1.8}
MAPPED_SOURCES = {"lidar", "refused"}


@pytest.fixture(scope="module")
def recording(tmp_path_factory):
    scans = []
    scan, mark = GridLevels._scan, GridLevels._set

    def observe_scan(grid, xy, k, ranges, along=None):
        grid._observed = []
        try:
            return scan(grid, xy, k, ranges, along)
        finally:
            marked = grid._observed
            del grid._observed
            scans.append({"k": k, "ramp": along is not None,
                          "cells": [{"cell": list(c), "occupied": o} for c, o in dict(marked).items()]})

    def observe_set(grid, c, occupied, source):
        if source == "lidar" and hasattr(grid, "_observed"):
            grid._observed.append((tuple(c), occupied))
        return mark(grid, c, occupied, source)

    out = tmp_path_factory.mktemp("scan-has-cells")
    with pytest.MonkeyPatch.context() as observe:
        observe.setattr(GridLevels, "_scan", observe_scan)
        observe.setattr(GridLevels, "_set", observe_set)
        verdict, path = run_b2.run(0, out_dir=out)
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return verdict, records, scans


def assert_scans_have_cells(records, scans):
    assert scans, "a real run must scan"
    for n, s in enumerate(scans):
        assert s["cells"], f"scan {n} at k {s['k']} put no cell in the map"
        levels = {c["cell"][2] for c in s["cells"]}
        assert levels == {s["k"]}, f"scan {n} at k {s['k']} marked cells at k {sorted(levels)}"
        assert any(not c["occupied"] for c in s["cells"]), f"scan {n} at k {s['k']} saw no free floor"
    scanned = {s["k"] for s in scans}
    for r in records:
        if r["kind"] == "level":
            assert k_of(FLOOR_Z[r["level"]]) in scanned, f"{r['level']} reached but never scanned"
    mapped = [r for r in records if r["kind"] == "mapped"]
    assert len(mapped) == 1, "the run logs the slab's measured cells once"
    assert isinstance(mapped[0].get("cells"), int) and mapped[0]["cells"] > 0, mapped[0]
    assert mapped[0]["sources"] and set(mapped[0]["sources"]) <= MAPPED_SOURCES, mapped[0]


def test_real_b2_run_passes(recording):
    verdict, _, _ = recording
    assert verdict["failed"] == [], verdict["failed"]


def test_every_real_scan_has_cells_at_its_own_level(recording):
    _, records, scans = recording
    assert_scans_have_cells(records, scans)
    assert len(scans) > 500
    assert any(s["ramp"] for s in scans) and any(not s["ramp"] for s in scans)   # ramp sweeps count too
    assert min(len(s["cells"]) for s in scans) >= 10


def test_each_floor_reached_was_scanned_there(recording):
    _, records, scans = recording
    levels = [r["level"] for r in records if r["kind"] == "level"]
    assert levels == ["L1", "ground", "B1", "B2"]
    per_floor = {lv: sum(s["k"] == k_of(FLOOR_Z[lv]) for s in scans) for lv in levels}
    assert all(n > 0 for n in per_floor.values()), per_floor


@pytest.mark.parametrize("mutation", ["empty_scan", "other_level", "only_walls", "unscanned_floor",
                                      "mapped_no_cells", "mapped_missing"])
def test_mutated_recording_cannot_pass(recording, mutation):
    _, records, scans = copy.deepcopy(recording)
    assert_scans_have_cells(records, scans)
    b2 = [s for s in scans if s["k"] == k_of(FLOOR_Z["B2"])]
    if mutation == "empty_scan":
        b2[0]["cells"] = []
    elif mutation == "other_level":
        b2[0]["cells"][0]["cell"][2] += 1
    elif mutation == "only_walls":
        b2[0]["cells"] = [c for c in b2[0]["cells"] if c["occupied"]]
    elif mutation == "unscanned_floor":
        scans = [s for s in scans if s not in b2]
    elif mutation == "mapped_no_cells":
        next(r for r in records if r["kind"] == "mapped")["cells"] = 0
    else:
        records = [r for r in records if r["kind"] != "mapped"]
    with pytest.raises(AssertionError):
        assert_scans_have_cells(records, scans)
