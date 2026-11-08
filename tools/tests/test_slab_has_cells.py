"""SLAB-HAS-CELLS: every slab shift in a real log lists the grid cells the slab covers, and they are right.

Real runs of tools/run_b2.py (seed 0) on B2 and B3. Each "shift" record carries "core" (the grid columns
[i, j] under the slab) and "footprint" (core grown by 0.05 m, what the stop and avoid checks use). From
each run's jsonl:
  - both are non-empty lists of integer [i, j] pairs, with no duplicates;
  - core matches the slab's real size: a 0.24 m x 0.24 m slab on 0.05 m cells is 5 x 5 = 25 columns, and
    footprint (one more ring) is 7 x 7 = 49; core lies inside footprint and holds the drop point "xy";
  - both equal what tools/run_b2.footprint() gives for that xy (the log is not edited after the fact);
  - the slab lies across the route the Scout was driving when it landed.
"""

import json
import math

import pytest

from tools.run_b2 import RES, SLAB_HALF, footprint, run

pytest.importorskip("mujoco")


@pytest.fixture(scope="module", params=["B2", "B3"])
def rows(request, tmp_path_factory):
    _, path = run(seed=0, out_dir=tmp_path_factory.mktemp(request.param.lower()), floor=request.param)
    return request.param, [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def shift(log):
    return next(r for r in log if r["kind"] == "shift")


def test_core_and_footprint_are_lists_of_integer_cells(rows):
    floor, log = rows
    s = shift(log)
    for key in ("core", "footprint"):
        cells = s[key]
        assert cells, f"{floor}: empty {key}"
        assert all(len(c) == 2 and all(type(v) is int for v in c) for c in cells), f"{floor}: {key} not [i, j]"
        assert len({tuple(c) for c in cells}) == len(cells), f"{floor}: duplicate cells in {key}"


def test_the_cells_match_the_slab_size_and_hold_the_drop_point(rows):
    floor, log = rows
    s = shift(log)
    core, foot = {tuple(c) for c in s["core"]}, {tuple(c) for c in s["footprint"]}
    side = math.ceil(2 * SLAB_HALF[0] / RES)                        # 0.24 m / 0.05 m -> 5 (rounded up)
    assert len(core) == side * side and len(foot) == (side + 2) ** 2, (floor, len(core), len(foot))
    assert core < foot
    x, y = s["xy"]
    assert (math.floor(x / RES), math.floor(y / RES)) in core


def test_the_logged_cells_are_what_the_runner_computes(rows):
    _, log = rows
    s = shift(log)
    assert {tuple(c) for c in s["core"]} == footprint(s["xy"])
    assert {tuple(c) for c in s["footprint"]} == footprint(s["xy"], margin=0.05)


def test_the_slab_lies_across_the_route_being_driven(rows):
    floor, log = rows
    s = shift(log)
    route = [r for r in log if r["kind"] == "plan" and r["t"] <= s["t"]][-1]
    assert {tuple(c) for c in s["core"]} & {tuple(c[:2]) for c in route["cells"]}, f"{floor}: slab off the route"
