"""POSE-HAS-FLOOR: every pose record of a real levels run carries a floor (level) that agrees with its
height and with the run's level transitions.

The log is the real tools/run_b2.py runner's (LevelWorld physics, nothing scripted). Its pose records are
{"t", "kind": "pose", "pos": [x, y, z], "state", "level", "cell": [i, j, k]} at 1 Hz, and "level" records
mark each floor reached. For every pose:
- "level" is one of L1, ground, B1, B2, B3 or ramp;
- on a named floor the Scout rides RIDE above that floor's height (sim.levels.LEVEL_Z), within its 0.02 m
  level tolerance; on "ramp" it is not at any floor's height;
- cell k is the floor's height in cells (sim.demo_descent.cell, from pos z minus RIDE).
And over the run: the named floors the poses pass through, in order, are the floors the level records
report, and the last pose is on the summary's final level.

B1 (about 10 s) runs every time; B2 and B3 are opt-in like the other real runs (RUN_B2_REAL=1).
"""

import json
import os

import pytest

pytest.importorskip("mujoco")

from sim.demo_descent import cell
from sim.levels import LEVEL_Z, RIDE
from tools.run_b2 import run

TOL = 0.02 + 0.001        # sim.levels.LevelWorld.level()'s tolerance, plus the log's 3-decimal rounding
FLOORS = [pytest.param("B1")] + [
    pytest.param(f, marks=pytest.mark.skipif(os.environ.get("RUN_B2_REAL") != "1",
                                             reason=f"real {f} run: set RUN_B2_REAL=1"))
    for f in ("B2", "B3")]


def dedupe(seq):
    return [x for n, x in enumerate(seq) if n == 0 or x != seq[n - 1]]


@pytest.mark.parametrize("floor", FLOORS)
def test_every_pose_has_a_floor_consistent_with_z_and_transitions(floor, tmp_path):
    _, path = run(seed=0, out_dir=tmp_path, floor=floor)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    poses = [r for r in records if r["kind"] == "pose"]
    assert len(poses) > 10

    for p in poses:
        assert p.get("level") in {*LEVEL_Z, "ramp"}, p
        floor_z = p["pos"][2] - RIDE
        near = [name for name, z in LEVEL_Z.items() if abs(floor_z - z) < TOL]
        if p["level"] == "ramp":
            assert not near, f"t={p['t']}: 'ramp' at the height of {near}"
        else:
            assert near == [p["level"]], f"t={p['t']}: level {p['level']} but z {p['pos'][2]}"
        assert p["cell"][2] == cell(p["pos"][0], p["pos"][1], floor_z)[2], p

    named = dedupe([p["level"] for p in poses if p["level"] != "ramp"])
    reported = [r["level"] for r in records if r["kind"] == "level"]
    assert named == reported, (named, reported)
    summary = next(r for r in records if r["kind"] == "summary")
    assert poses[-1]["level"] == summary["final_level"] == floor
