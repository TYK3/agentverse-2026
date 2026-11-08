"""b2: the Scout reaches basement B2 (z = -1.2) by driving ramp R3 down from B1, never teleported.

Scene: sim/scenes/levels.xml (written by sim/scenes/make_levels.py). R3 runs east over y 1.8..2.4,
from B1 at x = 2.5 down to B2 at x = 4.5, so its top face is z = -0.6 - 0.3 * (x - 2.5).
"""

from itertools import pairwise

import pytest

from sim.levels import LEVEL_Z, RIDE, LevelWorld, max_jump

B1, B2 = LEVEL_Z["B1"], LEVEL_Z["B2"]
# Hand-picked legs for the scripted-drive tests only: R2 to ground, R1 to B1, round R1's shaft wall,
# R3 to B2, out from R3's foot under its rail, west along y 1.5 (clear of B2's rubble and R4's rail)
# to casualty c2. The closed-loop test below is given none of these.
TO_B1 = [(1.2, 2.1, 0.6), (3.8, 2.1, 0.0), (3.8, 0.3, 0.0), (1.3, 0.3, B1)]
TO_B2 = [(1.35, 1.5, B1), (2.3, 2.1, B1), (4.75, 2.1, B2), (4.75, 1.5, B2), (0.75, 1.5, B2), (0.75, 0.8, B2)]


@pytest.fixture(scope="module")
def descent_b2():
    from sim.demo_descent import run
    return run(max_t=400.0, floor="B2")


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


def test_scripted_legs_reach_b2_on_r3_with_measured_heights_on_the_ramp():
    w = LevelWorld(render=False)
    drive_all(w, TO_B1)
    assert w.level() == "B1"
    n0 = len(w.trace)
    drive_all(w, TO_B2[:3])
    assert w.level() == "B2"
    assert w.pos[2] == pytest.approx(B2 + RIDE)
    # every pose on R3 sits RIDE above the ramp's top face: the height was measured, not set
    on_ramp = [(x, z) for _, x, y, z in w.trace[n0:] if 2.6 < x < 4.4 and 1.8 < y < 2.4]
    assert len(on_ramp) > 50
    for x, z in on_ramp:
        assert z - RIDE == pytest.approx(B1 - 0.3 * (x - 2.5), abs=0.01)
    zs = [z for _, z in on_ramp]
    assert all(b <= a + 1e-9 for a, b in pairwise(zs))   # only ever down
    drive_all(w, TO_B2[3:])
    assert w.level() == "B2"
    assert max_jump(w.trace) < 0.035                   # 0.3 m/s x 0.1 s plus the ramp's drop


def test_over_the_b2_goal_but_on_b1_is_not_arrival():
    w = LevelWorld(render=False)
    drive_all(w, TO_B1)
    assert drive(w, (0.75, 0.8, B2)) == "blocked"     # right (x, y), one level too high
    assert w.level() == "B1"


def test_the_b2_casualty_is_in_the_scene_below_b1():
    w = LevelWorld(render=False)
    assert w.m.body("casualty_c2").pos[2] == pytest.approx(B2 + 0.12)
    assert w._floor_at((3.0, 1.0), B1 - 0.1) == pytest.approx(B2)     # B2 floor under B1's slab


def test_closed_loop_descent_reaches_b2_without_teleport(descent_b2):
    """No waypoint, ramp or level is scripted: map, plan and drive until the Scout stands by c2 in B2."""
    assert descent_b2["reached"], descent_b2["log"][-5:]
    assert descent_b2["levels"] == ["L1", "ground", "B1", "B2"]
    assert descent_b2["max_jump"] < 0.035
    assert descent_b2["final_pos"][2] == pytest.approx(B2 + RIDE)


def test_responder_route_over_the_scouted_map_reaches_b2(descent_b2):
    assert descent_b2["responder_route"] == "ok"
    assert descent_b2["route_k"] == (12, -24)            # from L1 (k 12) down to B2 (k -24)
