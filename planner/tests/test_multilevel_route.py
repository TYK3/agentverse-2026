"""L4 multi-level A* (planner/levels.py) on hand-made maps: no sim needed."""

from itertools import pairwise

from planner.levels import find_route, waypoints

RES = 0.05


def floor(i, j, k, occupied=False):
    return {"cell": [i, j, k], "state": "seen", "occupied": occupied}


def two_levels(ramp=True, width=6):
    """Upper deck (k=6) for i 0..9, a ramp down 1 k per cell over i 10..15, lower deck (k=0) i 16..29,
    corridor j 0..width-1 between walls. Without `ramp` the upper deck simply ends above the lower one
    (a 0.3 m edge)."""
    cells = []
    for j in range(width):
        for i in range(30):
            if i < 10:
                cells.append(floor(i, j, 6))
            elif i < 16:
                if ramp:
                    cells.append(floor(i, j, 15 - i))
            else:
                cells.append(floor(i, j, 0))
            if not ramp and 10 <= i < 16:
                cells.append(floor(i, j, 0))
    for i in range(-1, 31):                       # side walls at every floor level, end walls
        for k in sorted({c["cell"][2] for c in cells if c["cell"][0] == min(max(i, 0), 29)}):
            cells += [floor(i, -1, k, occupied=True), floor(i, width, k, occupied=True)]
    for j in range(width):
        cells += [floor(-1, j, 6, occupied=True), floor(30, j, 0, occupied=True)]
    return {"t": 0, "res": RES, "cells": cells}


def test_route_changes_level_only_on_the_ramp():
    r = find_route(two_levels(), [], [2, 3, 6], [25, 3, 0])
    assert r["status"] == "ok"
    ks = [c[2] for c in r["cells"]]
    assert ks[0] == 6 and ks[-1] == 0
    assert max(abs(a - b) for a, b in pairwise(ks)) <= 1
    assert all(10 <= c[0] < 16 for c in r["cells"] if c[2] not in (0, 6))      # between levels = on the ramp


def test_goal_on_another_level_is_accepted_and_snapped():
    r = find_route(two_levels(), [], [2, 3, 6], [25, 3, 2])     # goal k is 2 off its floor
    assert r["status"] == "ok" and r["cells"][-1] == [25, 3, 0]


def test_an_edge_is_never_a_move():
    r = find_route(two_levels(ramp=False), [], [2, 3, 6], [25, 3, 0])
    assert r["status"] != "ok"


def test_unknown_goal_gives_a_frontier_toward_it():
    m = two_levels()
    m["cells"] = [c for c in m["cells"] if c["cell"][0] < 20 or c["occupied"]]   # floor half known
    r = find_route(m, [], [2, 3, 6], [27, 3, 0])
    assert r["status"] == "explore"
    assert r["frontier"][0] >= 17 and r["frontier"][2] == 0


def test_return_below_the_floor_is_not_an_obstacle():
    m = two_levels()
    # a ground-level return under the ramp (kk < k) must not block the ramp floor above it
    m["cells"] += [floor(12, j, 0, occupied=True) for j in range(6)]
    assert find_route(m, [], [2, 3, 6], [25, 3, 0])["status"] == "ok"
    # the same return at the ramp's own level is a kerb across it
    m["cells"] = [c for c in m["cells"] if c["cell"] != [12, 0, 0]]
    m["cells"] += [floor(13, j, 2, occupied=True) for j in range(6)]
    assert find_route(m, [], [2, 3, 6], [25, 3, 0])["status"] != "ok"


def test_waypoints_carry_floor_height():
    r = find_route(two_levels(), [], [2, 3, 6], [25, 3, 0])
    wps = waypoints(r["cells"], RES)
    assert wps[-1] == [round(25.5 * RES, 3), round(3.5 * RES, 3), 0.0]
    assert any(abs(w[2] - 0.3) < 1e-9 for w in wps[:-1])               # a point on the upper deck
    assert all(len(w) == 3 for w in wps)
