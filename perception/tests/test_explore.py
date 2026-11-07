"""T09 checks: frontier choice, hazards, re-look and planner priority, re-scan after a change, closed loop."""

import pytest

from perception.explore import Explorer
from perception.grid import Grid

K = 1
Z = 0.075


def corridor():
    """A seen, free 2 m x 0.75 m corridor along +x with walls on both sides; the far end is unknown."""
    g = Grid()
    for i in range(40):
        for j in range(-7, 8):
            g.free((i, j, K))
    for i in range(-1, 40):
        g.hit((i, -8, K))
        g.hit((i, 8, K))
    for j in range(-8, 9):
        g.hit((-1, j, K))                                   # the near end is a wall
    e = Explorer(g)
    e.on_sensors({"pose": {"pos": [0.1, 0.025, Z]}})
    return g, e


def test_heads_for_the_frontier():
    _, e = corridor()
    goto = e.tick(0.0)
    assert goto["reason"].startswith("frontier at cell [39, ")
    assert "unknown neighbours" in goto["reason"]
    assert 0.1 < goto["target"][0] <= 0.1 + 0.8             # a waypoint, not the far end: CARROT cells past the start ring
    assert goto["target"][2] == Z


def test_skips_hazard_cells():
    _, e = corridor()
    e.on_hazards([{"cell": [i, j, K], "status": "at_risk"} for i in range(20, 23) for j in range(-7, 8)])
    assert e.tick(0.0) is None                              # the only way on is through at_risk cells


def test_relook_first_then_planner_goto_holds():
    _, e = corridor()
    e.on_decision({"id": "d1", "outcome": "relook", "confidence": 0.4, "reason": "re-look at cell [10, 0, 1]"}, 0.0)
    goto = e.tick(0.0)
    assert goto["reason"].startswith("re-look at cell [10, 0, 1]")
    e.on_goto(goto, 0.0)                                    # our own message coming back does not hold
    e.on_goto({"target": [1.0, 0.0, Z], "reason": "planner"}, 0.0)
    assert e.tick(1.0) is None                              # the planner's scout/goto drives the Scout
    assert e.tick(21.0)["reason"].startswith("frontier")    # until the hold times out


def test_world_change_forgets_cells_near_moved_blocks():
    g, e = corridor()
    e.on_scene({"blocks": [{"id": "b7", "label": "debris", "pos": [1.0, 0.0, 0.5], "size": [0.05, 0.05, 0.5]}]})
    g.delta(0.0)
    e.on_change({"kind": "aftershock", "t": 1.0, "moved_blocks": ["b7"]})
    assert g.state((20, 0, K)) == "unknown" and g.state((5, 0, K)) == "seen"
    changed = g.delta(1.0)["cells"]
    assert changed and all(c["state"] == "unknown" for c in changed)
    assert e.tick(1.0)["reason"].startswith("re-scan after the aftershock moved b7")


# ---- closed loop on the backup scene (needs mujoco) -----------------------------

@pytest.fixture(scope="module")
def explored():
    pytest.importorskip("mujoco")
    from perception.tests.closed_loop import Loop
    loop = Loop()
    loop.run(90)
    return loop


@pytest.mark.parametrize("room, x0, x1", [("1", -1.45, -0.05), ("2", 0.05, 1.2), ("3", 1.3, 2.45)])
def test_scout_visits_every_room_unscripted(explored, room, x0, x1):
    assert any(x0 < x < x1 and -0.95 < y < 1.45 for x, y in explored.trail), f"room {room} never visited"


def test_rescans_moved_area_within_20_s(explored):
    explored.explorer.on_change({"kind": "aftershock", "t": explored.t, "moved_blocks": ["b11"]})
    forgot = set(explored.explorer.rescan)
    explored.run(20)
    back = sum(explored.grid.state(c) != "unknown" for c in forgot) / len(forgot)
    assert back > 0.8, f"only {back:.0%} of the moved area re-seen in 20 s"
    assert any(r.startswith("re-scan after the aftershock moved b11") for r in explored.reasons)


def test_waypoint_never_cuts_through_hazard_cells():
    _, e = corridor()
    e.on_hazards([{"cell": [i, j, K], "status": "at_risk"} for i in range(6, 9) for j in range(-7, 1)])
    goto = e.tick(0.0)
    assert goto is not None
    x0, y0 = 0.1, 0.025
    x1, y1 = goto["target"][:2]
    for s in range(101):
        x, y = x0 + (x1 - x0) * s / 100, y0 + (y1 - y0) * s / 100
        assert (int(x // 0.05), int(y // 0.05)) not in e.bad
