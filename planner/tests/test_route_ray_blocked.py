"""Ray-blocked cells stay occupied: the planner never re-proposes a route through a cell where the
Responder's collision ray hit something, whatever later map updates say (seed 2: re-proposed routes
through seen-free cells were blocked again and the supply was never placed).

The ray_hit record comes from the real Responder in the real World (backup scene) and is delivered
through the real hub Bus, so it also passes the log/decision contract. The map is planner input.
"""

import asyncio

import pytest

pytest.importorskip("mujoco")

from coord.hub import Bus  # noqa: E402
from planner.route import RoutePlanner  # noqa: E402
from sim import responder as R  # noqa: E402
from sim.world import World  # noqa: E402


def _real_ray_hit():
    """Drive the real Responder into wall b6 (as sim/tests/test_responder.py); return its log/decisions."""
    world = World(render=False)
    world._set_pose((-1.2, -1.7), 0.0)      # Scout parked out of the way
    sent = []
    r = R.Responder(world.m, world.d, publish=lambda topic, data: sent.append((topic, data)),
                    clock=lambda: world.t)
    r.on_route({"id": "rw", "robot": "responder", "cells": R.cells_along([(-0.48, -1.77), (-0.48, -0.6), (0.6, -0.6)]),
                "goal": "test", "model": "local-astar"})
    r.on_action({"action": "move", "route": "rw", "item": "water"})
    for _ in range(1200):
        r.step(0.1)
        world.tick(0.1)
        if r.state != "moving":
            break
    assert r.state == "blocked"
    return [d for t, d in sent if t == "log/decision"]


LOGS = None


def _logs():
    global LOGS
    if LOGS is None:
        LOGS = _real_ray_hit()
    return LOGS


def _free_map(cell, t=0.0, around=12):
    """A seen, free 0.05 m map around `cell` (the Scout saw nothing there, e.g. rubble under its LiDAR)."""
    x0, y0, _ = cell
    return {"t": t, "res": R.RES, "cells": [
        {"cell": [x, y, 0], "state": "seen", "occupied": False}
        for x in range(x0 - around, x0 + around + 1) for y in range(y0 - around, y0 + around + 1)]}


def _hit_cell(logs):
    hit = next(d for d in logs if d["outcome"] == "ray_hit")
    return tuple(int(n) for n in hit["perception"].rsplit("cell [", 1)[1].rstrip("]").split(", "))


async def _deliver(bus, logs):
    for data in logs:
        await bus.publish("log/decision", data)


def test_ray_hit_cell_is_never_routed_through_across_map_updates():
    logs = _logs()
    hit = _hit_cell(logs)
    start, goal = (hit[0] - 6, hit[1], 0), (hit[0] + 6, hit[1], 0)

    async def scenario():
        bus = Bus()
        router = RoutePlanner(bus)
        bus.subscribe("map/cells", router.update_map)
        await bus.publish("map/cells", _free_map(hit))
        before = await router.propose(start, goal, publish=False)
        # Control: on the free map the straight route runs through the hit cell.
        assert before["status"] == "ok" and list(hit) in before["cells"]

        await _deliver(bus, logs)                  # the real ray_hit, then the real "blocked"
        assert router.ray_blocked == {hit}
        after = await router.propose(start, goal, publish=False)
        assert after["status"] == "ok" and list(hit) not in after["cells"]

        # A later map update that says the cell is seen and free does not reopen it ...
        await bus.publish("map/cells", {"t": 1.0, "res": R.RES,
                                        "cells": [{"cell": list(hit), "state": "seen", "occupied": False}]})
        assert next(c for c in router.map_cells["cells"] if tuple(c["cell"]) == hit)["occupied"] is False
        again = await router.propose(start, goal, publish=False)
        assert again["status"] == "ok" and list(hit) not in again["cells"]
        # ... nor does a fresh full snapshot.
        await bus.publish("map/cells", _free_map(hit, t=2.0))
        last = await router.propose(start, goal, publish=False)
        assert last["status"] == "ok" and list(hit) not in last["cells"]

    asyncio.run(scenario())


def test_ray_hit_cell_missing_from_the_map_is_still_occupied():
    logs = _logs()
    hit = _hit_cell(logs)

    async def scenario():
        bus = Bus()
        router = RoutePlanner(bus)
        bus.subscribe("map/cells", router.update_map)
        free = _free_map(hit)
        free["cells"] = [c for c in free["cells"] if tuple(c["cell"]) != hit]
        await bus.publish("map/cells", free)
        await _deliver(bus, logs)
        route = await router.propose((hit[0] - 6, hit[1], 0), (hit[0] + 6, hit[1], 0), publish=False)
        assert route["status"] == "ok" and list(hit) not in route["cells"]
        assert not any(abs(x - hit[0]) <= 1 and abs(y - hit[1]) <= 1 for x, y, _ in route["cells"])

    asyncio.run(scenario())


def test_only_sim_ray_hits_mark_cells():
    logs = _logs()

    async def scenario():
        bus = Bus()
        router = RoutePlanner(bus)
        others = [d for d in logs if d["outcome"] != "ray_hit"]
        assert any(d["outcome"] == "blocked" for d in others)
        await _deliver(bus, others)
        hit = next(d for d in logs if d["outcome"] == "ray_hit")
        await bus.publish("log/decision", {**hit, "model": "local-astar"})   # not from the sim
        assert router.ray_blocked == set()

    asyncio.run(scenario())
