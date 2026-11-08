"""B2-E2E: an unscripted L1 -> B2 descent whose every 0.1 s pose is continuous and sits on a real floor.

sim.demo_descent.run(floor="B2") is the closed loop with nothing scripted: the Scout maps with its own
sensors (perception.levels), plans with the multi-level A* (planner.levels) and drives LevelWorld until it
stands by casualty c2 in B2. test_b2_descent.py checks the outcome and one number, max_jump. This test
checks every tick of the trace the run returns (t, x, y, z at 10 Hz):

  - cadence: one pose per 0.1 s tick from t 0, none missing or repeated;
  - speed: no tick moves more than SPEED x 0.1 s in xy, or MAX_JUMP in 3D;
  - support: every pose is RIDE above the floor that a fresh LevelWorld's own downward ray finds
    under it, so the height was measured, never set or floated;
  - floors: the Scout goes L1 -> ground -> B1 -> B2, leaving a floor only by ramp ticks and arriving at
    the next floor down (no lift, no skipped floor);
  - finish: on B2, beside the c2 marker, and the Scout's own map gives a route from L1 down to B2.

About 30 s of MuJoCo (GEMINI_MODE is not used: no model calls).
"""

import math
from itertools import pairwise

import pytest

pytest.importorskip("mujoco")

from sim.demo_descent import GOALS, run
from sim.levels import LEVEL_Z, RIDE, LevelWorld
from sim.world import SPEED

DT = 0.1
MAX_JUMP = 0.035           # metres per tick: 0.3 m/s x 0.1 s plus a ramp's drop (as run_b2 and test_b2_descent)
ON_FLOOR = 0.005           # metres: a pose's height may differ this much from RIDE above the measured floor
LEVEL_BAND = 0.02          # metres: within this of a LEVEL_Z height the Scout is on that floor (LevelWorld.level)
ORDER = ["L1", "ground", "B1", "B2"]


@pytest.fixture(scope="module")
def descent():
    return run(max_t=400.0, floor="B2")


@pytest.fixture(scope="module")
def trace(descent):
    return descent["trace"]


def level_of(z):
    floor = z - RIDE
    return next((name for name, h in LEVEL_Z.items() if abs(floor - h) < LEVEL_BAND), "ramp")


def test_the_unscripted_descent_reaches_c2_on_b2(descent, trace):
    assert descent["reached"], descent["log"][-5:]
    assert descent["levels"] == ORDER
    assert descent["plans"] > 10                     # it planned its way down: many re-plans, no script
    x, y, z = trace[-1][1:]
    assert level_of(z) == "B2"
    assert math.hypot(x - GOALS["B2"][0], y - GOALS["B2"][1]) < 0.15
    marker = LevelWorld(render=False).m.body("casualty_c2").pos
    assert math.hypot(x - marker[0], y - marker[1]) < 0.75


def test_one_pose_per_tick_from_t0(trace):
    assert trace[0][0] == 0.0 and len(trace) > 1000
    gaps = [(a[0], b[0]) for a, b in pairwise(trace) if abs((b[0] - a[0]) - DT) > 1e-6]
    assert not gaps, f"{len(gaps)} tick gap(s), first {gaps[:3]}"


def test_no_tick_moves_faster_than_the_scout_can_drive(trace):
    flat = [(a[0], math.dist(a[1:3], b[1:3])) for a, b in pairwise(trace)]
    full = [(a[0], math.dist(a[1:], b[1:])) for a, b in pairwise(trace)]
    worst_flat, worst_full = max(flat, key=lambda s: s[1]), max(full, key=lambda s: s[1])
    assert worst_flat[1] <= SPEED * DT + 1e-6, f"xy step {worst_flat[1]:.4f} m at t={worst_flat[0]:.1f}"
    assert worst_full[1] <= MAX_JUMP, f"3D step {worst_full[1]:.4f} m at t={worst_full[0]:.1f}"


def test_every_pose_rides_on_the_floor_measured_under_it(trace):
    probe = LevelWorld(render=False)
    probe.d.mocap_pos[probe.scout_mocap] = [-50.0, -50.0, 10.0]   # keep the probe's own Scout out of every ray
    off = []
    for t, x, y, z in trace:
        floor = probe._floor_at((x, y), z - RIDE + 0.05)
        if floor is None or abs(z - RIDE - floor) > ON_FLOOR:
            off.append((round(t, 1), round(z - RIDE, 3), None if floor is None else round(floor, 3)))
    assert not off, f"{len(off)} pose(s) not on the floor below them (t, floor z, measured), first {off[:3]}"


def test_floors_change_only_by_ramp_to_the_next_floor_down(trace):
    floors, last, ramp_ticks = [], None, 0
    for _, _, _, z in trace:
        here = level_of(z)
        if here == "ramp":
            ramp_ticks += 1
            continue
        if here != last:
            if last is not None:
                assert ramp_ticks > 0, f"{last} -> {here} without a ramp tick"
                step = abs(ORDER.index(here) - ORDER.index(last)) if here in ORDER else None
                assert step == 1, f"{last} -> {here} is not a neighbouring floor"
            floors.append(here)
            last = here
        ramp_ticks = 0
    assert floors == ORDER, floors


def test_the_scouts_own_map_routes_from_l1_to_b2(descent):
    assert descent["responder_route"] == "ok"
    assert descent["route_k"] == (12, -24)            # k 12 is L1's floor, k -24 is B2's
