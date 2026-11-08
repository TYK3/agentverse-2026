"""SHIFT-MAPPED-DELTA: after a slab shift the Scout's map gains occupied cells where the slab landed.

One real B2 rescue (tools/run_b2.py, the slab drops on the route to c2). The perception map is watched
from outside: GridLevels is wrapped so every add_sensors call books how many cells are occupied, in
the whole map and inside the slab's footprint (on the slab's floor), and drop_slab books the counts at
the moment of the shift. Nothing in the lanes or the runner is changed. Skips without MuJoCo.
"""

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def occupied(cells, area=None, k=None):
    """Occupied cells of a GridLevels map, optionally only those in `area` (i, j) within 3 levels of k."""
    return sum(1 for c, v in cells.items() if v["occupied"]
               and (area is None or ((c[0], c[1]) in area and abs(c[2] - k) <= 3)))


@pytest.fixture(scope="module")
def shift_run(tmp_path_factory):
    pytest.importorskip("mujoco")
    import run_b2

    import perception.levels as pl

    book = {"grid": None, "at_shift": None, "after": []}

    class Watched(pl.GridLevels):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            book["grid"] = self

        def add_sensors(self, msg):
            out = super().add_sensors(msg)
            if book["at_shift"] is not None:
                book["after"].append(occupied(self.cells))
            return out

    real_drop = run_b2.drop_slab

    def drop(world, xy, floor_z):
        cells = book["grid"].cells
        book["at_shift"] = occupied(cells)
        book["keys_at_shift"] = {c for c, v in cells.items() if v["occupied"]}
        return real_drop(world, xy, floor_z)

    mp = pytest.MonkeyPatch()
    mp.setattr(pl, "GridLevels", Watched)
    mp.setattr(run_b2, "drop_slab", drop)
    try:
        verdict, path = run_b2.run(seed=0, out_dir=tmp_path_factory.mktemp("shift"), floor="B2")
    finally:
        mp.undo()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    return verdict, records, book


def test_the_run_has_one_shift_then_a_mapped_record(shift_run):
    _, records, _ = shift_run
    shifts = [r for r in records if r["kind"] == "shift"]
    mapped = [r for r in records if r["kind"] == "mapped"]
    assert len(shifts) == 1, "expected exactly one slab shift on B2"
    assert len(mapped) == 1
    assert mapped[0]["t"] >= shifts[0]["t"]
    assert mapped[0]["cells"] > 0
    assert mapped[0]["sources"], "mapped cells must name the measurement that found them"


def test_slab_footprint_was_free_before_the_shift_and_occupied_after(shift_run):
    _, records, book = shift_run
    shift = next(r for r in records if r["kind"] == "shift")
    area = {tuple(c) for c in shift["footprint"]}
    k = round(-1.2 / 0.05)
    before = {c: {"occupied": True} for c in book["keys_at_shift"]}
    assert occupied(before, area, k) == 0, "slab footprint already occupied before the shift"
    assert occupied(book["grid"].cells, area, k) > 0, "slab footprint never mapped after the shift"


def test_total_occupied_cells_increase_after_the_shift(shift_run):
    _, _, book = shift_run
    before = book["at_shift"]
    assert book["after"], "no scans after the shift"
    assert max(book["after"]) > before, f"occupied cells never rose above {before} after the shift"


def test_the_shift_run_still_passes(shift_run):
    verdict, _, _ = shift_run
    assert verdict["failed"] == [], verdict["failed"]
