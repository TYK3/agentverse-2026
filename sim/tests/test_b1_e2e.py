"""B1 end to end: the Scout drives from L1 to B1 on the real levels scene.

GEMINI_MODE must be off. sim.demo_descent maps, plans and drives. This file
supplies no waypoint list and never writes a pose; LevelWorld's controller
does every move.
"""

import math
import os
import random
from functools import partial
from itertools import pairwise

import numpy as np

from sim import demo_descent
from sim.levels import LEVEL_Z, RIDE, LevelWorld
from sim.world import SPEED

# LevelWorld's default generator. The checked-in B1 golden
# (tools/tests/golden/b1_descent.jsonl) is this seed and arrives at 88.7
# sim seconds, which is 887 ticks of demo_descent.DT.
SEED = 0

# 1200 ticks is 120 sim seconds. Seed 0 finishes at tick 887, so this is
# slack for that same controller and a hard stop when it is still not on B1.
STEP_BUDGET = 1200

# xyz jump limit for one tick:
#     limit = SPEED * DT + MARGIN
# SPEED (sim/world.py) is the Scout controller's cap, 0.3 m/s, applied in
# LevelWorld._drive as a planar step. demo_descent ticks at DT = 0.1 s, so
# one tick changes xy by at most
#     SPEED * DT = 0.3 * 0.1 = 0.03 m.
# Each ramp in sim/scenes/make_levels.py drops 0.6 m over a 2.0 m run
# (slope 0.3). A full-speed tick on that slope also changes z by
#     0.3 * SPEED * DT = 0.009 m,
# and the straight-line xyz move is
#     hypot(0.03, 0.009) = 0.031321 m,
# 0.001321 m over the planar cap. MARGIN = 0.002 m covers that excess and
# leaves under a millimetre. Another full tick of travel (0.03 m) still fails.
MARGIN = 0.002

# Storey elevations, high to low. A z drop skips a floor when one tick's open
# z interval contains two or more of these. Adjacent floors are 0.6 m apart;
# a legal ramp tick drops about 0.009 m.
FLOORS = (LEVEL_Z["L1"], LEVEL_Z["ground"], LEVEL_Z["B1"], LEVEL_Z["B2"], LEVEL_Z["B3"])
LEVEL_BAND = 0.02  # LevelWorld.level() calls this band a named floor, else "ramp"


def _xyz(row):
    return row[1:]


def _evidence(step, pose, jump):
    x, y, z = pose
    return f"step {step} pose [{x:.6f}, {y:.6f}, {z:.6f}] jump {jump:.6f} m"


def _floor_name(z):
    floor = z - RIDE
    for name, level_z in LEVEL_Z.items():
        if abs(floor - level_z) < LEVEL_BAND:
            return name
    return "ramp"


def test_scout_drives_from_l1_to_b1_under_its_controller(monkeypatch):
    """Seed SEED, at most STEP_BUDGET controller ticks, no scripted waypoints."""
    assert os.environ.get("GEMINI_MODE", "off") == "off"
    assert FLOORS == (0.6, 0.0, -0.6, -1.2, -1.8)
    assert demo_descent.DT == 0.1

    random.seed(SEED)
    np.random.seed(SEED)
    monkeypatch.setattr(demo_descent, "LevelWorld", partial(LevelWorld, seed=SEED))

    out = demo_descent.run(max_t=STEP_BUDGET * demo_descent.DT, floor="B1")
    trace = out["trace"]
    limit = SPEED * demo_descent.DT + MARGIN
    steps = len(trace) - 1
    last_jump = math.dist(_xyz(trace[-2]), _xyz(trace[-1])) if steps else 0.0
    assert steps <= STEP_BUDGET, _evidence(steps, _xyz(trace[-1]), last_jump)
    assert _floor_name(trace[0][3]) == "L1", _evidence(0, _xyz(trace[0]), 0.0)

    for step, (prev, cur) in enumerate(pairwise(trace), start=1):
        jump = math.dist(_xyz(prev), _xyz(cur))
        pose = _xyz(cur)
        assert jump <= limit, _evidence(step, pose, jump)
        if cur[3] < prev[3]:
            crossed = [level_z for level_z in FLOORS if cur[3] < level_z < prev[3]]
            assert len(crossed) < 2, _evidence(step, pose, jump) + f" z drop crossed {crossed}"

    end_pose = _xyz(trace[-1])
    assert _floor_name(end_pose[2]) == "B1", (
        _evidence(steps, end_pose, last_jump) + f" level {_floor_name(end_pose[2])}"
    )
