"""POSE-HAS-FLOOR: every pose record of a real levels run carries a floor (level) that agrees with its
height and with the run's level transitions.

The log is the real tools/run_b2.py runner's (LevelWorld physics, nothing scripted). Its pose records are
{"t", "kind": "pose", "pos": [x, y, z], "state", "level", "cell": [i, j, k]} at 1 Hz, and "level" records
mark each floor reached. Complementary to #303 (POSE-LEVEL-Z), which checks height against the named floor and the ramp band
on the chained run; this file checks only what that does not, on single-floor runs:
- every pose's cell k is its floor's height in cells (sim.demo_descent.cell, from pos z minus RIDE);
- over the run, the named floors the poses pass through, in order, are the floors the level records
report, and the last pose is on the summary's final level.

B1 (about 10 s) runs every time; B2 and B3 are opt-in like the other real runs (RUN_B2_REAL=1).
"""

import json
import os

import pytest

pytest.importorskip("mujoco")

from sim.demo_descent import cell
from sim.levels import RIDE
from tools.run_b2 import run

FLOORS = [pytest.param("B1")] + [
    pytest.param(f, marks=pytest.mark.skipif(os.environ.get("RUN_B2_REAL") != "1",
                                             reason=f"real {f} run: set RUN_B2_REAL=1"))
    for f in ("B2", "B3")]


def dedupe(seq):
    return [x for n, x in enumerate(seq) if n == 0 or x != seq[n - 1]]


@pytest.mark.parametrize("floor", FLOORS)
def test_pose_cell_k_and_floor_transitions_agree_with_the_run(floor, tmp_path):
    _, path = run(seed=0, out_dir=tmp_path, floor=floor)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    poses = [r for r in records if r["kind"] == "pose"]
    assert len(poses) > 10

    for p in poses:
        assert p["cell"][2] == cell(p["pos"][0], p["pos"][1], p["pos"][2] - RIDE)[2], p

    named = dedupe([p["level"] for p in poses if p["level"] != "ramp"])
    reported = [r["level"] for r in records if r["kind"] == "level"]
    assert named == reported, (named, reported)
    summary = next(r for r in records if r["kind"] == "summary")
    assert poses[-1]["level"] == summary["final_level"] == floor
