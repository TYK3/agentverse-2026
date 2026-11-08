"""SUPPLY-RAY-R1R3 cause 2: on the hub, a re-plan after a collision-ray block starts where the Responder is.

Backup demo and B1 seed 3 on main d7f7f64: after a block, every new route started from the cell of an
earlier stop, about 2 m away, while the Responder sat 0.25 m from the goal (seed 3: r8-r29 all start at
[-12, -7] with the Responder at [29, 13]). The Responder turned back toward that first waypoint and hit
b11_rubble on all 21 of them. Loop.on_responder_decision re-plans from `start_cell()`, but planner.start
never wired it, so the hub's loop kept the mission's first start.
"""

import asyncio

from coord.hub import Bus
from planner import loop as L

RES = 0.05


def _free_map(x0=0, y0=0, n=40):
    return {"t": 1.0, "res": RES, "cells": [
        {"cell": [x, y, 0], "state": "seen", "occupied": False}
        for x in range(x0, x0 + n) for y in range(y0, y0 + n)]}


def _pose(x, y):
    return {"t": 2.0, "pos": [x, y, 0.05], "yaw": 0.0, "state": "blocked", "route": "r1", "carrying": []}


def _blocked(rid):
    return {"t": 2.0, "perception": "responder at [1.48, 0.67]", "model": "sim", "physics": "mujoco",
            "outcome": "blocked", "reason": f"collision ray: block ahead on route {rid}, stopped, "
                                            "dropped 2 queued action(s)"}


async def _hub_planner():
    import planner

    bus = Bus()
    router = await planner.start(bus)
    router.task.cancel()
    await asyncio.gather(router.task, return_exceptions=True)
    return bus, router


def test_the_hub_loop_follows_the_responder_pose():
    async def go():
        bus, router = await _hub_planner()
        await bus.publish("map/cells", _free_map())
        await bus.publish("responder/pose", _pose(1.48, 0.67))
        return router

    router = asyncio.run(go())
    assert callable(router.loop.start_cell)
    assert tuple(router.loop.start_cell()) == (29, 13, 0)


def test_a_block_replans_from_where_the_responder_stopped():
    async def go():
        bus, router = await _hub_planner()
        lp = router.loop
        await bus.publish("map/cells", _free_map())
        # A mission that began far from here, now executing r1 (as in seed 3 from r7 on)
        lp.mission_args = {"start": (3, 3, 0), "goal": (33, 16, 0), "goal_text": "deliver water to c1",
                           "item": "water", "casualty": "c1"}
        lp.route, lp.state = {"id": "r1", "cells": [[3, 3, 0], [33, 16, 0]]}, L.EXECUTING
        await bus.publish("responder/pose", _pose(1.48, 0.67))
        await bus.publish("log/decision", _blocked("r1"))
        return lp

    lp = asyncio.run(go())
    assert lp.state == L.IDLE
    assert tuple(lp.mission_args["start"]) == (29, 13, 0)
