"""POSE-CONTINUITY-B3: every tick of an unscripted L1-to-B3 descent is continuous.

The real demo runner feeds LevelWorld sensors into GridLevels, routes/probes
with planner.levels, and drives LevelWorld.goto/tick. Only the terminal B3 goal
is supplied; this test supplies no waypoints, pose edits, fake frames or mocks.
"""

import math
from itertools import pairwise

import pytest

from sim.demo_descent import DT, run

# Scout speed is 0.3 m/s and ticks are 0.1 s: horizontal travel <=0.030 m.
# The real scene's ramps have slope 0.3, so 3D travel <=0.030*sqrt(1+0.3**2)
# =0.03133 m. A fixed 0.035 m cap leaves <3.7 mm for ramp seams/roundoff,
# while rejecting a floor snap (0.6 m) or an ordinary cell teleport (0.05 m).
MAX_STEP_M = 0.035


def test_unscripted_l1_to_b3_has_no_discontinuous_pose_step():
    result = run(max_t=500.0, floor="B3")
    assert result["reached"], result["log"][-10:]
    assert result["levels"] == ["L1", "ground", "B1", "B2", "B3"]
    assert result["plans"] > 0

    trace = result["trace"]  # every tick, not the downsampled trail or rounded max_jump
    assert DT == pytest.approx(0.1)
    assert len(trace) == round(result["t"] / DT) + 1
    assert trace[0] == pytest.approx((0.0, 0.5, 0.5, 0.675))
    assert trace[-1][0] == pytest.approx(result["t"])
    assert trace[-1][3] == pytest.approx(-1.725)  # B3 floor -1.8 + sensor ride 0.075
    assert all(math.isfinite(value) for row in trace for value in row)

    # Check raw xyz for EVERY consecutive sample; a rounded aggregate can hide
    # an over-limit step, and checking only endpoints would miss a teleport.
    for step, (before, after) in enumerate(pairwise(trace), start=1):
        assert after[0] - before[0] == pytest.approx(0.1), (step, before, after)
        jump = math.dist(before[1:], after[1:])
        assert jump <= MAX_STEP_M, (
            f"step={step} t={before[0]:.3f}->{after[0]:.3f} "
            f"jump={jump:.9f}m cap={MAX_STEP_M}m "
            f"before={before[1:]} after={after[1:]}"
        )
