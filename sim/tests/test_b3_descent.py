"""b3: the Scout reaches basement B3 (z = -1.8) by driving ramp R4 down from B2, never teleported.

Scene: sim/scenes/levels.xml (written by sim/scenes/make_levels.py). R4 runs west over y 0..0.6, from
B2 at x = 4.5 down to B3 at x = 2.5. Every ramp drops 0.3 m per metre; RAMPS gives each one's top face,
so the measured trail can be checked against it point by point.
"""

from itertools import pairwise

import pytest

from sim.levels import LEVEL_Z, RIDE, LevelWorld, max_jump

B1, B2, B3 = LEVEL_Z["B1"], LEVEL_Z["B2"], LEVEL_Z["B3"]
SLOPE = 0.3
DROP = 0.6     # every ramp joins two levels 0.6 m apart
# name: (y0, y1, x at the top, z at the top, x at the foot), all from make_levels.py
RAMPS = {
    "R2": (1.8, 2.4, 1.5, 0.6, 3.5),
    "R1": (0.0, 0.6, 3.5, 0.0, 1.5),
    "R3": (1.8, 2.4, 2.5, B1, 4.5),
    "R4": (0.0, 0.6, 4.5, B2, 2.5),
}
# Hand-picked legs for the scripted-drive tests only (the closed-loop test is given none of these):
# R2 to ground, R1 to B1, R3 to B2, out from R3's foot, R4 to B3, out from R4's foot under its rail,
# then west to casualty c3.
TO_B2 = [(1.2, 2.1, 0.6), (3.8, 2.1, 0.0), (3.8, 0.3, 0.0), (1.3, 0.3, B1),
         (1.35, 1.5, B1), (2.3, 2.1, B1), (4.75, 2.1, B2), (4.75, 0.6, B2)]
TO_B3 = [(4.75, 0.3, B2), (2.0, 0.3, B3), (2.0, 1.0, B3), (0.75, 1.6, B3)]


@pytest.fixture(scope="module")
def descent_b3():
    from sim.demo_descent import run
    return run(max_t=500.0, floor="B3")


def drive(w, target, max_ticks=600):
    w.goto({"target": list(target), "reason": "test"})
    for _ in range(max_ticks):
        w.tick(0.1)
        if w.state != "moving":
            break
    return w.state


def drive_all(w, legs):
    for leg in legs:
        assert drive(w, leg) == "arrived", (leg, w.level(), w.pos.tolist())


def ramp_floor(name, x):
    """Height of ramp `name`'s top face at x."""
    _, _, x_top, z_top, _ = RAMPS[name]
    return z_top - SLOPE * abs(x - x_top)


def on_ramp(trace, name, margin=0.1):
    """(x, floor z) of every pose over the inside of ramp `name` (margin off each end), on that ramp.

    Ramps share plan-view strips with others above or below them (and the Scout may drive under
    one), so a pose counts only if its floor lies strictly between that ramp's two levels."""
    y0, y1, x_top, z_top, x_foot = RAMPS[name]
    lo, hi = sorted((x_top, x_foot))
    out = []
    for _, x, y, z in trace:
        floor = z - RIDE
        if lo + margin < x < hi - margin and y0 < y < y1 and z_top - DROP + 0.02 < floor < z_top - 0.02:
            out.append((x, floor))
    return out


def test_scripted_legs_reach_b3_on_r4_with_measured_heights_on_the_ramp():
    w = LevelWorld(render=False)
    drive_all(w, TO_B2)
    assert w.level() == "B2"
    n0 = len(w.trace)
    drive_all(w, TO_B3[:2])
    assert w.level() == "B3"
    assert w.pos[2] == pytest.approx(B3 + RIDE)
    pts = on_ramp(w.trace[n0:], "R4")
    assert len(pts) > 50
    for x, floor in pts:
        assert floor == pytest.approx(ramp_floor("R4", x), abs=0.01)
    assert all(b <= a + 1e-9 for (_, a), (_, b) in pairwise(pts))       # only ever down
    drive_all(w, TO_B3[2:])
    assert w.level() == "B3"
    assert max_jump(w.trace) < 0.035


def test_over_the_b3_goal_but_on_b2_is_not_arrival():
    w = LevelWorld(render=False)
    drive_all(w, TO_B2)
    drive_all(w, [(4.75, 1.5, B2), (0.75, 1.5, B2)])  # the right spot, one level up
    assert drive(w, (0.75, 1.5, B3)) == "blocked"
    assert w.level() == "B2"


def test_the_b3_casualty_and_floor_are_under_b2():
    w = LevelWorld(render=False)
    assert w.m.body("casualty_c3").pos[2] == pytest.approx(B3 + 0.12)
    assert w._floor_at((3.0, 1.0), B2 - 0.1) == pytest.approx(B3)


def test_closed_loop_descent_reaches_b3_without_teleport(descent_b3):
    """No waypoint, ramp or level is scripted: map, plan and drive until the Scout stands by c3 in B3."""
    assert descent_b3["reached"], descent_b3["log"][-5:]
    assert descent_b3["levels"] == ["L1", "ground", "B1", "B2", "B3"]
    assert descent_b3["max_jump"] < 0.035
    assert descent_b3["final_pos"][2] == pytest.approx(B3 + RIDE)


@pytest.mark.parametrize("name", ["R2", "R1", "R3", "R4"])
def test_closed_loop_heights_on_every_ramp_are_the_ramp_surface(descent_b3, name):
    """Intermediate xyz: on each of the four ramps the unscripted run's poses sit on the ramp face."""
    pts = on_ramp(descent_b3["trace"], name)
    assert len(pts) >= 20, name
    worst = max(abs(floor - ramp_floor(name, x)) for x, floor in pts)
    assert worst < 0.01, (name, worst)


def test_closed_loop_floor_heights_are_only_levels_or_ramps(descent_b3):
    """Every pose stands on a level or on a ramp face: none hangs between them."""
    for _, x, y, z in descent_b3["trace"]:
        floor = z - RIDE
        if any(abs(floor - lz) < 0.01 for lz in LEVEL_Z.values()):
            continue
        assert any(abs(floor - ramp_floor(n, x)) < 0.01 and RAMPS[n][0] <= y <= RAMPS[n][1] for n in RAMPS), \
            (x, y, floor)


def test_responder_route_over_the_scouted_map_reaches_b3(descent_b3):
    assert descent_b3["responder_route"] == "ok"
    assert descent_b3["route_k"] == (12, -36)            # from L1 (k 12) down to B3 (k -36)
