"""LEVEL-TRANSITION: every change of level in a real run is a drive down (or up) a ramp, never a jump.

A real tools/run_b2.py run to B3 (seed 0: L1 -> ground -> B1 -> B2 -> B3, the Scout's closed loop, a slab
on B3). From its jsonl ("level" records when the Scout reaches a floor, "pose" records every second):
  - level changes go only between adjacent levels of the stack, and the first pass is L1, ground, B1,
    B2, B3 in order;
  - at each "level" record the Scout's pose is at that floor's height (floor + ride height);
  - height changes no faster than a ramp allows: between poses one second apart, |dz| <= MAX_DZ
    (0.3 m/s along a 0.3 m-per-metre ramp is 0.09 m, plus slack);
  - going from one floor to the next takes at least MIN_RAMP_S: a ramp is 2 m long and the Scout drives
    at 0.3 m/s, so a level change in less time would be a jump.
"""

import json
from itertools import pairwise

import pytest

from sim.levels import LEVEL_Z
from tools.run_b2 import run

pytest.importorskip("mujoco")

ORDER = ["L1", "ground", "B1", "B2", "B3"]
RIDE = 0.075
MAX_DZ = 0.11         # metres per 1 s pose step
MIN_RAMP_S = 6.0      # 2 m of ramp at 0.3 m/s is 6.7 s


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    _, path = run(seed=0, out_dir=tmp_path_factory.mktemp("b3"), floor="B3")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def levels(rows):
    return [r for r in rows if r["kind"] == "level"]


def test_levels_change_only_between_neighbours_and_first_go_down_in_order(rows):
    seq = [r["level"] for r in levels(rows)]
    assert seq[:5] == ORDER, seq
    for a, b in pairwise(seq):
        assert abs(ORDER.index(a) - ORDER.index(b)) == 1, f"{a} -> {b} skips a level"


def test_each_level_is_reached_at_its_floor_height(rows):
    poses = [r for r in rows if r["kind"] == "pose"]
    for lv in levels(rows)[1:]:
        near = min(poses, key=lambda p: abs(p["t"] - lv["t"]))
        assert abs(near["t"] - lv["t"]) <= 1.0
        assert near["pos"][2] == pytest.approx(LEVEL_Z[lv["level"]] + RIDE, abs=0.1), (lv, near)


def test_height_changes_no_faster_than_a_ramp_allows(rows):
    poses = [r for r in rows if r["kind"] == "pose"]
    assert len(poses) > 100
    for a, b in pairwise(poses):
        dt = b["t"] - a["t"]
        assert abs(b["pos"][2] - a["pos"][2]) <= MAX_DZ * max(dt, 1.0), (a, b)


def test_a_floor_to_floor_trip_takes_at_least_a_ramp_drive(rows):
    lv = levels(rows)
    for a, b in pairwise(lv):
        assert b["t"] - a["t"] >= MIN_RAMP_S, f"{a['level']} -> {b['level']} in {b['t'] - a['t']:.1f} s"
