"""L4: the Scout changes level only by driving on real ramps (sim/levels.py, sim/demo_descent.py)."""

import pytest

from sim import levels
from sim.levels import RIDE, LevelWorld, max_jump


@pytest.fixture(scope="module")
def descent():
    from sim.demo_descent import run
    return run(max_t=400.0)


def drive(w, target, max_ticks=400):
    w.goto({"target": list(target), "reason": "test"})
    for _ in range(max_ticks):
        w.tick(0.1)
        if w.state != "moving":
            break
    return w.state


def test_scout_starts_on_l1_at_ride_height():
    w = LevelWorld(render=False)
    assert w.level() == "L1"
    assert w.pos[2] == pytest.approx(0.6 + RIDE)


def test_ramp_r2_takes_the_scout_down_to_the_ground_floor():
    w = LevelWorld(render=False)
    assert drive(w, (1.2, 2.1, 0.6)) == "arrived"
    assert drive(w, (3.8, 2.1, 0.0)) == "arrived"
    assert w.level() == "ground"
    assert max_jump(w.trace) < 0.035                   # 0.3 m/s x 0.1 s plus the ramp's rise


def test_right_spot_on_the_wrong_level_is_not_arrival():
    w = LevelWorld(render=False)                       # on L1 above the ground floor
    assert drive(w, (0.5, 0.5, 0.0)) == "blocked"
    assert w.level() == "L1"


def test_a_drop_is_refused_and_the_scout_stays_put(monkeypatch):
    w = LevelWorld(render=False)
    start = w.pos.copy()
    monkeypatch.setattr(w, "_floor_at", lambda xy, z: w.floor_z - 0.5)   # a 0.5 m hole ahead
    assert drive(w, (1.0, 0.5, 0.6), max_ticks=5) == "blocked"
    assert w.pos[:2] == pytest.approx(start[:2])
    assert w.pos[2] == pytest.approx(start[2])


def test_levels_scene_loads_with_the_names_world_needs():
    m = LevelWorld(render=False).m
    for body in ("ground", "scout", "casualty_c1"):
        assert m.body(body) is not None
    assert levels.LEVELS.name == "levels.xml"


def test_closed_loop_descent_reaches_b1_without_teleport(descent):
    """No waypoint, ramp or level is scripted: map, plan and drive until the Scout stands by c1 in B1."""
    assert descent["reached"], descent["log"][-5:]
    assert descent["levels"] == ["L1", "ground", "B1"]
    assert descent["max_jump"] < 0.035


def test_responder_route_over_the_scouted_map_spans_all_levels(descent):
    assert descent["responder_route"] == "ok"
    assert descent["route_k"] == (12, -12)            # from L1 (k 12) down to B1 (k -12)
