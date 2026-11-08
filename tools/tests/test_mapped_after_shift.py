"""MAPPED-AFTER-SHIFT: a generated B2 log's mapped beat matches newly sensed slab cells.

The runner logs counts/sources, not individual mapped coordinates. Passive observers
retain the real mapper's cells to check that beat against the physical slab footprint.
Neither observer replaces physics, sensors, mapping, planning, or runner decisions.
"""

import copy
import json

import pytest

from perception.levels import GridLevels
from tools import run_b2


@pytest.fixture(scope="module")
def recording(tmp_path_factory):
    evidence = {"grid": None, "shifted": False, "scans": {}}
    add_sensors, drop_slab = GridLevels.add_sensors, run_b2.drop_slab

    def observe_scan(grid, data):
        result = add_sensors(grid, data)
        evidence["grid"] = grid
        if evidence["shifted"]:
            evidence["scans"][round(data["t"], 2)] = {
                cell: record.copy() for cell, record in grid.cells.items()
                if record["occupied"] and cell[:2] in evidence["area"]
                and abs(cell[2] - evidence["k"]) <= 3
            }
        return result

    def observe_drop(world, xy, floor_z):
        # Freeze actual observations before the real drop, not a made-up free map.
        evidence["area"] = run_b2.footprint(xy, margin=0.05)
        evidence["core"] = run_b2.footprint(xy)
        evidence["k"] = round(floor_z / run_b2.RES)
        evidence["before"] = {cell for cell, record in evidence["grid"].cells.items()
                              if record["occupied"]}
        drop_slab(world, xy, floor_z)
        evidence["shifted"] = True

    with pytest.MonkeyPatch.context() as observe:
        observe.setattr(GridLevels, "add_sensors", observe_scan)
        observe.setattr(run_b2, "drop_slab", observe_drop)
        _, path = run_b2.run(seed=0, floor="B2", out_dir=tmp_path_factory.mktemp("real-b2-shift"))
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return records, evidence


def assert_slab_mapped(records, evidence):
    shifts = [(i, r) for i, r in enumerate(records) if r["kind"] == "shift"]
    assert len(shifts) == 1, "a real B2 slab shift is required; no fabricated substitute"
    shift_index, shift = shifts[0]
    assert shift["level"] == "B2"
    mapped = [(i, r) for i, r in enumerate(records) if r["kind"] == "mapped"]
    assert len(mapped) == 1, "the log must include a mapped beat"
    mapped_index, mapped = mapped[0]
    assert mapped_index > shift_index and mapped["t"] > shift["t"]
    assert mapped["cells"] > 0
    measured = evidence["scans"][mapped["t"]]
    assert mapped["cells"] == len(measured)
    assert mapped["sources"] == sorted({r["source"] for r in measured.values()})
    assert "lidar" in mapped["sources"]
    assert set(map(tuple, shift["core"])) == evidence["core"]
    # Existing walls cannot satisfy the test: new LiDAR returns must be inside
    # the slab itself, on B2, and absent from the pre-drop occupied map.
    new_slab_hits = {cell for cell, r in measured.items()
                     if cell[:2] in evidence["core"] and cell[2] == -24
                     and r["state"] == "seen" and r["source"] == "lidar"
                     and cell not in evidence["before"]}
    assert new_slab_hits, "fresh LiDAR must map the newly landed slab, not a nearby old wall"
    verdict = records[-1]
    assert verdict["kind"] == "verdict"
    assert verdict["steps"]["slab mapped from the Scout's own measurements"]["ok"] is True


def test_real_b2_log_maps_new_slab_after_shift(recording):
    assert_slab_mapped(*recording)


@pytest.mark.parametrize("mutation", ["missing", "empty", "before_shift", "wrong_source"])
def test_mutated_real_log_cannot_claim_the_slab_was_mapped(recording, mutation):
    records, evidence = recording
    records = copy.deepcopy(records)
    mapped = next(r for r in records if r["kind"] == "mapped")
    if mutation == "missing":
        records.remove(mapped)
    elif mutation == "empty":
        mapped["cells"] = 0
    elif mutation == "before_shift":
        mapped["t"] = next(r["t"] for r in records if r["kind"] == "shift") - 0.1
    else:
        mapped["sources"] = ["trail"]
    with pytest.raises(AssertionError):
        assert_slab_mapped(records, evidence)
