"""B2-LOCK: the real L1 -> ground -> B1 -> B2 descent, locked as a standalone regression (like #196 for B1).

Nothing is scripted: sim.demo_descent's closed loop (LevelWorld physics, perception.levels map,
planner.levels A*) finds all three ramps by itself. What is locked:
  - the outcome: the Scout reaches casualty c2 on B2 via L1, ground, B1, B2, never teleported, and a
    Responder route over the map it built spans L1 (k 12) to B2 (k -24);
  - the physics: every trail cell between two floors lies on ramp R2, R1 or R3, at that ramp's
    measured height (the Scout's height is the floor under it, never set);
  - all three ramps were driven, and the trail never stood on a level below B2;
  - determinism: two runs are identical (no wall clock, no unseeded randomness in the loop);
  - a budget: sim time and plan count stay within 1.5x of the measured baseline (176.4 s and
    259 plans on 2026-11-08).

Scene geometry (sim/scenes/make_levels.py): L1 0.6, ground 0, B1 -0.6, B2 -1.2, slopes 0.3 m per metre.
R2: y 1.8..2.4, x 1.5 (L1) -> 3.5 (ground). R1: y 0..0.6, x 3.5 (ground) -> 1.5 (B1).
R3: y 1.8..2.4, x 2.5 (B1) -> 4.5 (B2), below R2 in plan, so a cell is matched to the ramp at its height.
"""

import pytest

from sim.levels import LEVEL_Z

RES = 0.05
FLOORS = {round(LEVEL_Z[n] / RES) for n in ("L1", "ground", "B1", "B2")}      # 12, 0, -12, -24
BASELINE_T, BASELINE_PLANS = 176.4, 259
SLACK = 0.10     # metres of footprint and cell rounding around a ramp

# name: (x0, x1, y0, y1, floor z at x0, floor z at x1)
RAMPS = {
    "R2": (1.5, 3.5, 1.8, 2.4, 0.6, 0.0),
    "R1": (1.5, 3.5, 0.0, 0.6, -0.6, 0.0),
    "R3": (2.5, 4.5, 1.8, 2.4, -0.6, -1.2),
}


def ramps_under(x, y):
    """{ramp name: floor height} for every ramp whose plan footprint (grown by SLACK) holds (x, y)."""
    out = {}
    for name, (x0, x1, y0, y1, z0, z1) in RAMPS.items():
        if x0 - SLACK <= x <= x1 + SLACK and y0 - SLACK <= y <= y1 + SLACK:
            u = (min(max(x, x0), x1) - x0) / (x1 - x0)
            out[name] = z0 + u * (z1 - z0)
    return out


@pytest.fixture(scope="module")
def runs():
    from sim.demo_descent import run
    return run(max_t=500.0, floor="B2"), run(max_t=500.0, floor="B2")


def matched_ramp(cell):
    """The ramp a between-floors trail cell sits on, at its height, or None."""
    i, j, k = cell
    x, y = (i + 0.5) * RES, (j + 0.5) * RES
    for name, z in ramps_under(x, y).items():
        if abs(k * RES - z) <= 0.05:
            return name
    return None


def test_b2_descent_outcome_is_locked(runs):
    out = runs[0]
    assert out["reached"], out["log"][-5:]
    assert out["levels"] == ["L1", "ground", "B1", "B2"]
    assert out["max_jump"] < 0.035                       # 0.3 m/s x 0.1 s plus a ramp's rise: no teleport
    assert out["final_pos"][2] == pytest.approx(LEVEL_Z["B2"] + 0.075)
    assert out["responder_route"] == "ok"
    assert tuple(out["route_k"]) == (12, -24)


def test_levels_change_only_on_ramps_at_the_ramp_height(runs):
    between = [c for c in runs[0]["trail"] if c[2] not in FLOORS]
    assert between, "the trail never crossed a ramp"
    for c in between:
        assert matched_ramp(c) is not None, (
            f"k {c[2]} at ({(c[0] + 0.5) * RES:.2f}, {(c[1] + 0.5) * RES:.2f}) is on no ramp at that height")


def test_all_three_ramps_were_driven_and_nothing_below_b2(runs):
    driven = {matched_ramp(c) for c in runs[0]["trail"] if c[2] not in FLOORS}
    assert {"R2", "R1", "R3"} <= driven, driven
    assert min(c[2] for c in runs[0]["trail"]) >= round(LEVEL_Z["B2"] / RES)


def test_the_closed_loop_is_deterministic(runs):
    a, b = runs
    for key in ("t", "plans", "levels", "final_pos", "max_jump", "route_k", "trail", "log"):
        assert a[key] == b[key], key


def test_time_and_plans_stay_near_the_baseline(runs):
    out = runs[0]
    assert out["t"] <= BASELINE_T * 1.5, f"{out['t']} s against a {BASELINE_T} s baseline"
    assert out["plans"] <= BASELINE_PLANS * 1.5, f"{out['plans']} plans against {BASELINE_PLANS}"
