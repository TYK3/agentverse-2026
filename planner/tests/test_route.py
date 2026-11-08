import asyncio
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from planner import start
from planner.route import find_route

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def doorway():
    return json.loads((FIXTURES / "map__cells.json").read_text(encoding="utf-8"))


@pytest.fixture
def room():
    return {
        "t": 0,
        "res": 0.1,
        "cells": [
            {"cell": [x, y, 0], "state": "seen", "occupied": False}
            for x in range(7) for y in range(5)
        ],
    }


def change_cell(map_cells, cell, **changes):
    record = next(r for r in map_cells["cells"] if r["cell"] == list(cell))
    record.update(changes)


def hazard(cell, status):
    return {"cell": list(cell), "status": status, "why": "test", "estimate": True}


def test_shortest_path_in_open_room(room):
    route = find_route(room, [], (0, 0, 0), (6, 4, 0))
    assert route["status"] == "ok"
    assert route["cells"][0] == [0, 0, 0]
    assert route["cells"][-1] == [6, 4, 0]
    assert len(route["cells"]) == 7
    assert route["cost"] == pytest.approx(0.1 * (4 * math.sqrt(2) + 2))


@pytest.mark.parametrize("status", ["at_risk", "collapsed"])
def test_routes_around_hazard(room, status):
    route = find_route(room, [hazard((3, 2, 0), status)], (0, 2, 0), (6, 2, 0))
    assert route["status"] == "ok"
    assert [3, 2, 0] not in route["cells"]
    assert route["cost"] > 0.6


def test_collapsed_doorway_has_no_verified_route(doorway):
    result = find_route(doorway, [hazard((3, 2, 0), "collapsed")], (0, 2, 0), (6, 2, 0))
    assert result == {"status": "no_verified_route", "needs": "re-look", "cells": []}


@pytest.mark.parametrize("state", ["inferred", "unknown"])
def test_unobserved_doorway_is_a_relook_target_not_a_route(doorway, state):
    change_cell(doorway, (3, 2, 0), state=state)
    result = find_route(doorway, [], (0, 2, 0), (6, 2, 0))
    assert result == {
        "status": "no_verified_route", "needs": "re-look", "cells": [[3, 2, 0]]
    }


@pytest.mark.parametrize("state", ["inferred", "unknown"])
def test_goes_around_unobserved_cells_when_possible(room, state):
    change_cell(room, (3, 2, 0), state=state)
    route = find_route(room, [], (0, 2, 0), (6, 2, 0))
    assert route["status"] == "ok"
    assert [3, 2, 0] not in route["cells"]


def test_missing_doorway_is_unknown_and_needs_a_relook(doorway):
    doorway["cells"] = [r for r in doorway["cells"] if r["cell"] != [3, 2, 0]]
    result = find_route(doorway, [], (0, 2, 0), (6, 2, 0))
    assert result["status"] == "no_verified_route"
    assert result["cells"] == [[3, 2, 0]]


def test_clearance_prefers_a_longer_path_away_from_rubble(room):
    change_cell(room, (3, 1, 0), occupied=True)
    result = find_route(room, [], (0, 2, 0), (6, 2, 0))
    assert result["status"] == "ok"
    assert result["cost"] < 5
    assert any(c[1] > 2 for c in result["cells"])
    for x, y, _ in result["cells"][1:]:
        assert math.hypot(x - 3, y - 1) * room["res"] > 0.15


@pytest.mark.parametrize("res, expected_cost", [(0.15, 5.15), (0.16, 0.16)])
def test_clearance_threshold_is_measured_in_metres(res, expected_cost):
    corridor = {
        "res": res,
        "cells": [
            {"cell": [0, 0, 0], "state": "seen", "occupied": False},
            {"cell": [1, 0, 0], "state": "seen", "occupied": False},
            {"cell": [1, 1, 0], "state": "seen", "occupied": True},
        ],
    }
    result = find_route(corridor, [], (0, 0, 0), (1, 0, 0))
    assert result["cost"] == pytest.approx(expected_cost)


@pytest.mark.parametrize("blocker", ["occupied", "inferred", "unknown", "collapsed"])
def test_diagonal_never_cuts_a_blocked_corner(blocker):
    grid = {
        "res": 0.1,
        "cells": [
            {"cell": [x, y, 0], "state": "seen", "occupied": False}
            for x in range(2) for y in range(2)
        ],
    }
    hazards = []
    for cell in [(0, 1, 0), (1, 0, 0)]:
        if blocker == "occupied":
            change_cell(grid, cell, occupied=True)
        elif blocker in ("inferred", "unknown"):
            change_cell(grid, cell, state=blocker)
        else:
            hazards.append(hazard(cell, blocker))
    assert find_route(grid, hazards, (0, 0, 0), (1, 1, 0))["status"] == "no_verified_route"


def test_upper_layer_cannot_bypass_collapsed_door(doorway):
    doorway["cells"] += [
        {"cell": [x, 2, 1], "state": "seen", "occupied": False} for x in range(7)
    ]
    result = find_route(doorway, [hazard((3, 2, 0), "collapsed")], (0, 2, 0), (6, 2, 0))
    assert result["status"] == "no_verified_route"


def test_frontiers_are_nearest_goal_first_and_never_known_hazards(room):
    for record in room["cells"]:
        if record["cell"][0] >= 3:
            record["state"] = "unknown"
    result = find_route(room, [hazard((3, 2, 0), "at_risk")], (0, 2, 0), (6, 2, 0))
    assert result["status"] == "no_verified_route"
    assert result["cells"] == [[3, 1, 0], [3, 3, 0], [3, 0, 0], [3, 4, 0]]


@pytest.mark.parametrize("endpoint", ["start", "goal"])
@pytest.mark.parametrize("state", ["inferred", "unknown"])
def test_unobserved_endpoints_are_not_traversable(room, endpoint, state):
    cell = (0, 0, 0) if endpoint == "start" else (6, 4, 0)
    change_cell(room, cell, state=state)
    assert find_route(room, [], (0, 0, 0), (6, 4, 0))["status"] == "no_verified_route"


def test_start_is_goal_still_requires_safe_cell(room):
    assert find_route(room, [], (2, 2, 0), (2, 2, 0)) == {
        "status": "ok", "cells": [[2, 2, 0]], "cost": 0.0
    }
    result = find_route(room, [hazard((2, 2, 0), "collapsed")], (2, 2, 0), (2, 2, 0))
    assert result["status"] == "no_verified_route"


@pytest.mark.parametrize("res", [0, -0.1, float("nan"), float("inf"), True])
def test_invalid_resolution_fails_closed(room, res):
    room["res"] = res
    with pytest.raises(ValueError, match="resolution"):
        find_route(room, [], (0, 0, 0), (6, 4, 0))


def test_ambiguous_duplicate_cell_fails_closed(room):
    room["cells"].append({"cell": [0, 0, 0], "state": "unknown", "occupied": True})
    with pytest.raises(ValueError, match="duplicate"):
        find_route(room, [], (0, 0, 0), (6, 4, 0))


class RecordingBus:
    def __init__(self):
        self.subscribers = {}
        self.history = []

    def subscribe(self, topic, callback):
        self.subscribers.setdefault(topic, []).append(callback)

    async def publish(self, topic, data):
        self.history.append({"topic": topic, "data": data})
        for callback in self.subscribers.get(topic, []):
            result = callback(data)
            if asyncio.iscoroutine(result):
                await result


def test_bus_uses_latest_snapshots_and_only_publishes_success(doorway):
    async def scenario():
        bus = RecordingBus()
        planner = await start(bus)
        missing = await planner.propose((0, 2, 0), (6, 2, 0))
        assert missing["status"] == "no_verified_route"
        assert bus.history == []

        await bus.publish("map/cells", doorway)
        await bus.publish("map/hazards", [])
        first = await planner.propose((0, 2, 0), (6, 2, 0))
        assert first["proposal"] == {
            "id": "r1", "robot": "responder", "cells": [[x, 2, 0] for x in range(7)],
            "goal": "deliver water to c1", "model": "local-astar",
        }

        await bus.publish("map/hazards", [hazard((3, 2, 0), "collapsed")])
        failed = await planner.propose((0, 2, 0), (6, 2, 0))
        assert failed["status"] == "no_verified_route"
        assert len([m for m in bus.history if m["topic"] == "route/proposed"]) == 1

        await bus.publish("map/hazards", [])
        second = await planner.propose((0, 2, 0), (6, 2, 0), goal_text="deliver radio to c2")
        assert second["proposal"]["id"] == "r2"
        assert second["proposal"]["goal"] == "deliver radio to c2"

        changed_map = json.loads(json.dumps(doorway))
        change_cell(changed_map, (3, 2, 0), state="inferred")
        await bus.publish("map/cells", changed_map)
        assert (await planner.propose((0, 2, 0), (6, 2, 0)))["status"] == "no_verified_route"
        assert {m["topic"] for m in bus.history} == {"map/cells", "map/hazards", "route/proposed"}

    asyncio.run(scenario())


def test_fake_run_emits_a_labelled_development_route():
    process = subprocess.run(
        [sys.executable, "-m", "planner.fake_run"],
        cwd=FIXTURES.parents[1], capture_output=True, text=True, check=True,
    )
    envelope = json.loads(process.stdout)
    assert envelope["topic"] == "route/proposed"
    assert envelope["data"]["model"] == "local-astar"
    assert envelope["data"]["cells"][0] == [0, 2, 0]
    assert envelope["data"]["cells"][-1] == [6, 2, 0]
    assert "DEVELOPMENT FIXTURES" in process.stderr
    assert "physics verification pending" in process.stderr


def test_map_deltas_keep_observations_and_revoke_changed_cells(doorway):
    async def scenario():
        planner = await start(RecordingBus())
        planner.update_map(doorway)
        planner.update_map({"t": 1, "res": 0.1, "cells": []})
        assert (await planner.propose((0, 2, 0), (6, 2, 0)))["status"] == "ok"
        planner.update_map({"t": 2, "res": 0.1, "cells": [
            {"cell": [3, 2, 0], "state": "unknown", "occupied": False}
        ]})
        result = await planner.propose((0, 2, 0), (6, 2, 0))
        assert result == {
            "status": "no_verified_route", "needs": "re-look", "cells": [[3, 2, 0]]
        }
        planner.update_map({"t": 3, "res": 0.1, "cells": [
            {"cell": [3, 2, 0], "state": "seen", "occupied": False}
        ]})
        assert (await planner.propose((0, 2, 0), (6, 2, 0)))["status"] == "ok"
        # The consumer must not rewrite the producer's payload.
        assert len(doorway["cells"]) == 35

    asyncio.run(scenario())


def test_new_resolution_discards_old_grid(doorway):
    async def scenario():
        planner = await start(RecordingBus())
        planner.update_map(doorway)
        planner.update_map({"t": 1, "res": 0.05, "cells": []})
        assert (await planner.propose((0, 2, 0), (6, 2, 0)))["status"] == "no_verified_route"

    asyncio.run(scenario())


def test_fake_run_can_load_external_fixtures_and_report_no_path(tmp_path, doorway):
    map_path, hazards_path = tmp_path / "map.json", tmp_path / "hazards.json"
    map_path.write_text(json.dumps(doorway), encoding="utf-8")
    hazards_path.write_text(json.dumps([hazard((3, 2, 0), "collapsed")]), encoding="utf-8")
    process = subprocess.run(
        [sys.executable, "-m", "planner.fake_run", "--map", str(map_path),
         "--hazards", str(hazards_path)],
        cwd=FIXTURES.parents[1], capture_output=True, text=True, check=False,
    )
    assert process.returncode == 1
    assert json.loads(process.stdout) == {
        "status": "no_verified_route", "needs": "re-look", "cells": []
    }


def test_fake_run_accepts_hub_fixture_envelopes(tmp_path, doorway):
    map_path, hazards_path = tmp_path / "map.json", tmp_path / "hazards.json"
    map_path.write_text(json.dumps({"topic": "map/cells", "data": doorway}), encoding="utf-8")
    hazards_path.write_text(json.dumps({"topic": "map/hazards", "data": []}), encoding="utf-8")
    process = subprocess.run(
        [sys.executable, "-m", "planner.fake_run", "--map", str(map_path),
         "--hazards", str(hazards_path)],
        cwd=FIXTURES.parents[1], capture_output=True, text=True, check=True,
    )
    assert json.loads(process.stdout)["data"]["cells"] == [[x, 2, 0] for x in range(7)]


# ---- X1: predicted at_risk cells are avoided pre-emptively, entered only when there is no other way ----

def test_at_risk_doorway_is_entered_only_when_it_is_the_only_way(doorway):
    """No detour exists, so the route goes through the predicted cell (the loop then asks enter_at_risk)."""
    result = find_route(doorway, [hazard((3, 2, 0), "at_risk")], (0, 2, 0), (6, 2, 0))
    assert result["status"] == "ok"
    assert [3, 2, 0] in result["cells"]
    assert result["cost"] >= 50


def test_route_keeps_a_margin_from_predicted_failures():
    """Open 9x9 room, at_risk cell in the middle: the route avoids the cell and the cells around it."""
    room = {"res": 0.05, "cells": [{"cell": [x, y, 0], "state": "seen", "occupied": False}
                                   for x in range(9) for y in range(9)]}
    result = find_route(room, [hazard((4, 4, 0), "at_risk")], (0, 4, 0), (8, 4, 0))
    assert result["status"] == "ok"
    assert all(max(abs(c[0] - 4), abs(c[1] - 4)) >= 3 for c in result["cells"]), result["cells"]
    assert result["cost"] < 5


def test_physics_rejected_cells_stay_impassable(doorway):
    """The loop marks physics-rejected cells "blocked": never routed through, even as the only way."""
    rejected = {**hazard((3, 2, 0), "at_risk"), "blocked": True}
    assert find_route(doorway, [rejected], (0, 2, 0), (6, 2, 0))["status"] == "no_verified_route"


def test_exclusion_zone_is_never_entered_even_as_the_only_way(doorway):
    """L5: perception sensed debris moving here; the keep-out zone is a wall until fresh scans lift it."""
    zone = {**hazard((3, 2, 0), "at_risk"), "exclusion": True}
    assert find_route(doorway, [zone], (0, 2, 0), (6, 2, 0))["status"] == "no_verified_route"
    assert find_route(doorway, [{**zone, "exclusion": False}], (0, 2, 0), (6, 2, 0))["status"] == "ok"


# ---- the Responder's width on the real 0.05 m map ----

def fine_room(width_cells, length=20, res=0.05):
    """A corridor `width_cells` free cells wide between two occupied rows, at perception's resolution."""
    cells = []
    for x in range(length):
        for y in range(-1, width_cells + 1):
            cells.append({"cell": [x, y, 0], "state": "seen", "occupied": y in (-1, width_cells)})
    return {"res": res, "cells": cells}


def test_route_keeps_the_responder_body_off_obstacles():
    """0.14 m wide: no route cell centre closer than 0.10 m to an occupied cell (>= 0.075 m to its face)."""
    room = fine_room(9)                                     # 0.45 m wide
    result = find_route(room, [], (0, 4, 0), (19, 4, 0))
    assert result["status"] == "ok"
    assert all(1 <= c[1] <= 7 for c in result["cells"]), result["cells"]


def test_gap_narrower_than_the_responder_has_no_route():
    assert find_route(fine_room(2), [], (0, 0, 0), (19, 1, 0))["status"] == "no_verified_route"   # 0.10 m
    assert find_route(fine_room(3), [], (0, 1, 0), (19, 1, 0))["status"] == "ok"                  # 0.15 m


def test_breach_cells_exactly_ten_centimetres_from_rubble_stay_usable():
    """A 0.2 m breach (4 cells): its only usable cells are exactly 0.10 m from an occupied cell centre."""
    room = fine_room(9)
    for c in room["cells"]:                    # a wall across x=10 with a 4-cell breach at y 3..6
        if c["cell"][0] == 10 and not 3 <= c["cell"][1] <= 6:
            c["occupied"] = True
    result = find_route(room, [], (0, 4, 0), (19, 4, 0))
    assert result["status"] == "ok"
    crossing = [c for c in result["cells"] if c[0] == 10]
    assert crossing and all(c[1] in (4, 5) for c in crossing), crossing


def test_responder_parked_against_a_wall_can_back_out():
    result = find_route(fine_room(9), [], (0, 0, 0), (19, 4, 0))
    assert result["status"] == "ok" and result["cells"][0] == [0, 0, 0]


def test_responder_holds_when_goal_would_overlap_an_occupied_casualty():
    room = fine_room(9)
    room["cells"] = [c if c["cell"] != [19, 5, 0] else {**c, "occupied": True} for c in room["cells"]]
    result = find_route(room, [], (0, 4, 0), (19, 4, 0))   # the casualty's body is mapped at [19, 5]
    assert result["status"] == "no_verified_route"  # 0.05 m offset cannot fit the 0.14 m chassis
    result = find_route(room, [], (0, 4, 0), (14, 4, 0))  # stop short; the arm places the supply ahead
    assert result["status"] == "ok" and result["cells"][-1] == [14, 4, 0]
