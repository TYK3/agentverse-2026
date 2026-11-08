"""ROUTE-HAS-LEN: every route in a real rescue run log has a length: a connected path of cells with a real
length in metres, from where the Scout planned it to its goal.

A route is a "plan" record with status "ok" (planner.levels.find_route found the goal; "explore" plans
go to a frontier and are not routes). tools/run_b2.py logs each one with its cells. Run once for real
per target floor (seed 0: B2 and B3, each with its slab shift), every route must have at least two cells,
each step one of the planner's own moves (an 8-neighbour cell, at most MAX_DK levels), so it has a
length in metres (steps times the grid resolution) that is positive and no shorter than the straight line
between its ends; and it must end on the goal's column, within the planner's SNAP_DK of the goal's level.
"""

import copy
import itertools
import json
import math

import pytest

pytest.importorskip("mujoco")    # a real sim run; CI's tools lane has no MuJoCo (the full job does)

from planner.levels import MAX_DK, NEIGHBOURS, SNAP_DK
from sim.demo_descent import GOALS, RES, cell
from tools import run_b2

FLOORS = ("B2", "B3")


@pytest.fixture(scope="module", params=FLOORS)
def recording(request, tmp_path_factory):
    floor = request.param
    verdict, path = run_b2.run(0, out_dir=tmp_path_factory.mktemp(f"route-has-len-{floor}"), floor=floor)
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return floor, verdict, records


def routes(records):
    return [r for r in records if r["kind"] == "plan" and r.get("status") == "ok"]


def length_m(cells):
    """A route's length in metres: its steps, cell centre to cell centre (k steps are RES high)."""
    return RES * sum(math.dist(a, b) for a, b in itertools.pairwise(cells))


def assert_routes_have_length(records, floor):
    rs = routes(records)
    assert rs, "a real run must plan at least one route"
    goal = cell(*GOALS[floor])
    for r in rs:
        cells = r.get("cells")
        assert isinstance(cells, list) and len(cells) >= 2, f"route at {r['t']} s has no length: {cells}"
        for a, b in itertools.pairwise(cells):
            assert (b[0] - a[0], b[1] - a[1]) in NEIGHBOURS and abs(b[2] - a[2]) <= MAX_DK, \
                f"route at {r['t']} s jumps {a} -> {b}"
        n = length_m(cells)
        assert n > 0 and n + 1e-9 >= RES * math.dist(cells[0], cells[-1]), (r["t"], n)
        end = cells[-1]
        assert end[:2] == goal[:2] and abs(end[2] - goal[2]) <= SNAP_DK, f"route at {r['t']} s ends at {end}"


def test_real_run_passes(recording):
    floor, verdict, _ = recording
    assert verdict["failed"] == [], (floor, verdict["failed"])


def test_every_real_route_has_length(recording):
    floor, _, records = recording
    assert_routes_have_length(records, floor)
    shift = next(r for r in records if r["kind"] == "shift")
    after = [r for r in routes(records) if r["t"] > shift["t"]]
    assert after, "the re-planned routes after the slab shift are routes too"
    assert all(0.2 <= length_m(r["cells"]) <= 5.0 for r in routes(records))   # one floor's room, not a jump


def test_explore_plans_are_not_routes(recording):
    _, _, records = recording
    plans = [r for r in records if r["kind"] == "plan"]
    assert {r["status"] for r in plans} >= {"ok", "explore"}
    assert len(routes(records)) < len(plans)


@pytest.mark.parametrize("mutation", ["one_cell", "no_cells", "gap", "repeat", "level_jump", "wrong_end"])
def test_mutated_route_cannot_pass(recording, mutation):
    floor, _, records = copy.deepcopy(recording)
    assert_routes_have_length(records, floor)
    r = routes(records)[-1]
    if mutation == "one_cell":
        r["cells"] = r["cells"][-1:]
    elif mutation == "no_cells":
        del r["cells"]
    elif mutation == "gap":
        del r["cells"][len(r["cells"]) // 2]
        r["cells"][0] = [r["cells"][0][0] - 2, r["cells"][0][1], r["cells"][0][2]]
    elif mutation == "repeat":
        r["cells"].insert(1, list(r["cells"][0]))
    elif mutation == "level_jump":
        r["cells"][1] = [r["cells"][1][0], r["cells"][1][1], r["cells"][1][2] + MAX_DK + 1]
    else:
        r["cells"][-1] = [r["cells"][-1][0] + 1, r["cells"][-1][1], r["cells"][-1][2]]
    with pytest.raises(AssertionError):
        assert_routes_have_length(records, floor)
