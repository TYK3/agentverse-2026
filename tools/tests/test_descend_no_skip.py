"""DESCEND-NO-SKIP: a live multi-floor run descends one storey at a time.

tools/run_b2.py, seed 0, GEMINI_MODE=off. Floor names and heights are
sim.levels.LEVEL_Z: L1, ground, B1, B2, B3 at 0.6, 0, -0.6, -1.2, -1.8 m.
Consecutive repeats of a logged level collapse. Each change is the next lower
storey. Pose z may cross at most one storey boundary between samples.
"""

import json
from itertools import pairwise

import pytest

pytest.importorskip("mujoco")

from sim.levels import LEVEL_Z, RIDE
from tools.run_b2 import PATHS, run

# Declared top to bottom in sim.levels.LEVEL_Z.
L1, ground, B1, B2, B3 = LEVEL_Z
STOREYS = (L1, ground, B1, B2, B3)


def pose_boundaries():
    """Mid-plane between each pair of floors, in the pose frame.

    A pose record's z is the sensor origin, RIDE above the floor.
    """
    height = [LEVEL_Z[name] + RIDE for name in STOREYS]
    return [(left + right) / 2 for left, right in pairwise(height)]


def collapsed(rows, kind):
    """(record index, level, t) with consecutive repeats of the same level removed.

    Pose records report ramp between floors. A ramp is not a storey.
    """
    picked = []
    for index, row in enumerate(rows):
        if row["kind"] != kind:
            continue
        level = row["level"]
        if kind == "pose" and level == "ramp":
            continue
        picked.append((index, level, row["t"]))
    out = []
    for item in picked:
        if not out or out[-1][1] != item[1]:
            out.append(item)
    return out


def boundaries_between(z0, z1):
    lo, hi = sorted((z0, z1))
    return [bound for bound in pose_boundaries() if lo < bound < hi]


def assert_one_storey_at_a_time(rows, floor):
    assert STOREYS == ("L1", "ground", "B1", "B2", "B3")
    assert [LEVEL_Z[name] for name in STOREYS] == [0.6, 0.0, -0.6, -1.2, -1.8]
    expect = list(STOREYS[: STOREYS.index(floor) + 1])
    assert expect == PATHS[floor]
    for kind in ("level", "pose"):
        levels = collapsed(rows, kind)
        assert [level for _, level, _ in levels] == expect, (kind, levels)
        for (_, prev, _), (index, level, t) in pairwise(levels):
            assert prev in STOREYS and level in STOREYS, (kind, index, prev, level)
            step = STOREYS.index(level) - STOREYS.index(prev)
            # LEVEL_Z runs downward. The next logged storey is the next name.
            # A higher name is an ascent and fails this check.
            assert step >= 0, f"ascent at record {index} t={t}: {prev} -> {level}"
            assert step == 1, f"skip at record {index} t={t}: {prev} -> {level}"
    poses = [(index, row) for index, row in enumerate(rows) if row["kind"] == "pose"]
    assert len(poses) >= 2
    for (_, prev), (index, row) in pairwise(poses):
        z0, z1 = prev["pos"][2], row["pos"][2]
        crossed = boundaries_between(z0, z1)
        # LevelWorld accepts a higher or lower floor within MAX_RISE (the step
        # test uses abs), so pose z may rise across one boundary. Two is a skip.
        assert len(crossed) <= 1, (
            f"pose z crossed {len(crossed)} storey boundaries at record {index} "
            f"t={row['t']}: {z0} -> {z1} ({prev['level']} -> {row['level']})"
        )


@pytest.mark.slow
@pytest.mark.parametrize("floor", [B2, B3])
def test_live_descent_never_skips_a_storey(tmp_path, monkeypatch, floor):
    monkeypatch.setenv("GEMINI_MODE", "off")
    _, path = run(seed=0, out_dir=tmp_path, floor=floor)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert_one_storey_at_a_time(rows, floor)
