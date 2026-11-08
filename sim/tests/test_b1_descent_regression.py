"""B1-LOCK (ref #114): the real, supported L1 -> ground -> B1 descent, locked as a standalone regression.

Nothing is scripted: sim.demo_descent's closed loop (LevelWorld physics, perception.levels map,
planner.levels A*) finds both ramps by itself. What is locked:
  - the outcome: the Scout reaches casualty c1 on B1 via L1, ground, B1, never teleported, and a
    Responder route over the map it built spans L1 (k 12) to B1 (k -12);
  - the physics: every trail cell between two floors lies on ramp R2 or R1, at that ramp's measured
    height (the Scout's height is the floor under it, never set);
  - determinism: the loop has no wall clock and no unseeded randomness, so two runs are identical;
  - a budget: sim time and plan count stay near the measured baseline (88.7 s, 129 plans on
    2026-11-08), with room for a better planner but not for a much worse one.

Scene geometry (sim/scenes/make_levels.py): L1 at z = 0.6, ground 0, B1 -0.6. R2 runs east over
y 1.8..2.4 from L1 at x = 1.5 to ground at x = 3.5; R1 runs west over y 0..0.6 from ground at x = 3.5
to B1 at x = 1.5. Both slope 0.3 m per metre.
"""

import pytest

from sim.levels import LEVEL_Z

RES = 0.05
FLOORS = {round(z / RES) for name, z in LEVEL_Z.items() if name in ("L1", "ground", "B1")}   # 12, 0, -12
BASELINE_T, BASELINE_PLANS = 88.7, 129
SLACK = 0.10     # metres of footprint and cell rounding around a ramp


def ramp_floor(x, y):
    """Floor height of ramp R2 or R1 under (x, y), or None if (x, y) is on neither."""
    if 1.5 - SLACK <= x <= 3.5 + SLACK:
        if 1.8 - SLACK <= y <= 2.4 + SLACK:
            return 0.6 - 0.3 * (min(max(x, 1.5), 3.5) - 1.5)          # R2: L1 -> ground, heading east
        if -SLACK <= y <= 0.6 + SLACK:
            return -0.3 * (3.5 - min(max(x, 1.5), 3.5))               # R1: ground -> B1, heading west
    return None


@pytest.fixture(scope="module")
def runs():
    from sim.demo_descent import run
    return run(max_t=400.0, floor="B1"), run(max_t=400.0, floor="B1")


def test_b1_descent_outcome_is_locked(runs):
    out = runs[0]
    assert out["reached"], out["log"][-5:]
    assert out["levels"] == ["L1", "ground", "B1"]
    assert out["max_jump"] < 0.035                       # 0.3 m/s x 0.1 s plus a ramp's rise: no teleport
    assert out["final_pos"][2] == pytest.approx(LEVEL_Z["B1"] + 0.075)
    assert out["responder_route"] == "ok"
    assert tuple(out["route_k"]) == (12, -12)


def test_levels_change_only_on_ramps_at_the_ramp_height(runs):
    between = [c for c in runs[0]["trail"] if c[2] not in FLOORS]
    assert between, "the trail never crossed a ramp"
    for i, j, k in between:
        x, y = (i + 0.5) * RES, (j + 0.5) * RES
        z = ramp_floor(x, y)
        assert z is not None, f"level change off the ramps at ({x:.2f}, {y:.2f}), k {k}"
        assert k * RES == pytest.approx(z, abs=0.05), f"k {k} at ({x:.2f}, {y:.2f}); ramp floor {z:.3f}"


def test_both_ramps_were_driven(runs):
    on = {"R2": 0, "R1": 0}
    for i, j, k in runs[0]["trail"]:
        if k in FLOORS:
            continue
        y = (j + 0.5) * RES
        on["R2" if y > 1.2 else "R1"] += 1
    assert on["R2"] > 0 and on["R1"] > 0, on


def test_the_closed_loop_is_deterministic(runs):
    a, b = runs
    for key in ("t", "plans", "levels", "final_pos", "max_jump", "route_k", "trail", "log"):
        assert a[key] == b[key], key


def test_time_and_plans_stay_near_the_baseline(runs):
    out = runs[0]
    assert out["t"] <= BASELINE_T * 1.5, f"{out['t']} s against a {BASELINE_T} s baseline"
    assert out["plans"] <= BASELINE_PLANS * 1.5, f"{out['plans']} plans against {BASELINE_PLANS}"
