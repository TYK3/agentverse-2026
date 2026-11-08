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


def test_world_change_revisits_predicted_cells_nearest_first_without_block_poses():
    g, e = corridor()
    e.on_hazards([{"cell": [30, 0, 0], "status": "at_risk"}, {"cell": [31, 0, 0], "status": "at_risk"},
                  {"cell": [60, 0, 0], "status": "at_risk"}])
    n = len(g.cells)
    e.on_change({"kind": "aftershock", "t": 1.0, "moved_blocks": ["b7"]})
    assert len(g.cells) == n                                # nothing forgotten: the scan diff needs the old map
    assert [v[0] for v in e.visits] == [(30, 0, 0), (60, 0, 0)]     # one visit per 0.5 m patch, nearest first
    goto = e.tick(1.0)
    assert goto["reason"] == "re-scan after the aftershock: predicted at-risk cell [30, 0, 0]"
    e.on_sensors({"pose": {"pos": [1.2, 0.025, Z]}})        # within LOOK (1 m) of cell 30: the LiDAR sees it
    assert e.tick(2.0)["reason"] == "re-scan after the aftershock: predicted at-risk cell [60, 0, 0]"


def test_scan_diff_cells_are_visited():
    _, e = corridor()
    e.on_diff([(35, 2, K)])
    assert e.tick(0.0)["reason"] == "re-scan where the scan changed: cell [35, 2, 0]"


def test_frontiers_outside_the_building_are_skipped():
    """An open yard: walls only to the north, so no frontier is enclosed on 3 sides."""
    g = Grid()
    for i in range(-20, 20):
        for j in range(-20, 8):
            g.free((i, j, K))
        g.hit((i, 8, K))
    e = Explorer(g)
    e.on_sensors({"pose": {"pos": [0.0, 0.0, Z]}})
    assert e.tick(0.0) is None


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


def test_after_a_real_shake_the_scout_rescans_and_keeps_out_of_debris():
    """The test world moves b8, b10 and b11; perception hears only "aftershock". Within 30 s the Scout has
    re-scanned (scan diff on), never stood in a collapsed cell, and spent under 10% of the time in cells
    that turned at_risk (debris found right next to it, or after its last decision)."""
    pytest.importorskip("mujoco")
    from perception.tests.closed_loop import Loop
    loop = Loop()
    loop.run(90)
    loop.aftershock()
    statuses = []
    for _ in range(300):
        loop.step()
        x, y = loop.pos[:2]
        statuses.append(loop.hazards.status((int(x // 0.05), int(y // 0.05))))
    assert loop.grid.appeared and loop.grid.cleared
    assert any(r.startswith("re-scan") for r in loop.reasons)
    assert "collapsed" not in statuses
    assert statuses.count("at_risk") / len(statuses) < 0.1


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
