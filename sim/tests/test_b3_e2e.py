"""End-to-end B3: one real chained descent, L1 then B1, B2 and B3.

``tools.run_levels.run`` (seed 0) is the merged rescue loop: one world, one map,
one planner, and no reset between legs. The Scout must finish on B3 beside
casualty c3, and no frame-to-frame pose step may exceed 0.3 m.
"""

import math
import os
from itertools import pairwise

import pytest

from sim.demo_descent import GOALS
from sim.levels import LEVEL_Z, RIDE, LevelWorld
from tools import run_levels as rl

# A driven step is about 0.03 m per 0.1 s frame. 0.3 m between frames is a teleport.
JUMP_LIMIT_M = 0.3
ORDER = ["L1", "ground", "B1", "B2", "B3"]


@pytest.fixture(scope="module")
def records():
    os.environ.setdefault("GEMINI_MODE", "off")
    return rl.run(seed=0)


def _summary(records):
    return next(r for r in records if r["kind"] == "summary")


def test_scout_ends_on_b3(records):
    meta = records[0]
    assert meta["kind"] == "meta" and meta["seed"] == 0 and meta["source"] == "tools/run_levels.py"
    levels = [r["level"] for r in records if r["kind"] == "level"]
    assert levels == ORDER, levels
    final = _summary(records)["final_pos"]
    assert final[2] == pytest.approx(LEVEL_Z["B3"] + RIDE, abs=0.02), final


def test_casualty_c3_is_located(records):
    """Each leg's casualty is the person on that floor; c3 is the one beside the finish."""
    legs = [r for r in records if r["kind"] == "leg"]
    assert [(r["floor"], r["casualty"], r["reached"]) for r in legs] == [
        ("B1", "c1", True), ("B2", "c2", True), ("B3", "c3", True),
    ], legs
    final = _summary(records)["final_pos"]
    goal = GOALS["B3"]
    assert math.dist(final[:2], goal[:2]) < rl.NEAR, (final, goal)
    marker = LevelWorld(render=False).m.body("casualty_c3").pos
    assert float(marker[2]) == pytest.approx(LEVEL_Z["B3"] + 0.12)
    apart = math.dist(final[:2], (float(marker[0]), float(marker[1])))
    assert apart < 0.75, (apart, final, [round(float(v), 3) for v in marker])


def test_no_frame_to_frame_pose_jump_exceeds_0_3_m(records):
    """Consecutive Scout poses are one sim frame (0.1 s) apart; ``max_jump`` is the largest step.

    The run log also stores a pose each second. At 0.3 m/s those samples are about
    0.30 m apart on a flat floor and about 0.31 m on a ramp, so they are not the frame step.
    """
    summary = _summary(records)
    jump = summary["max_jump"]
    poses = [r["pos"] for r in records if r["kind"] == "pose"]
    samples = [math.dist(a, b) for a, b in pairwise(poses)]
    worst = max(samples) if samples else None
    assert jump is not None and jump <= JUMP_LIMIT_M, (
        f"max_jump={jump} m exceeds {JUMP_LIMIT_M} m "
        f"(largest 1 Hz pose sample {worst} m, final {summary['final_pos']})"
    )
