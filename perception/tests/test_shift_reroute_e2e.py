"""SHIFT-REROUTE-E2E (ref #31/#144, after #209): debris shifts onto a mapped route, end to end from MuJoCo LiDAR
through the Scout's grid and map/cells messages into the planner's RoutePlanner.

The backup scene, room 2. The Scout maps the room from (0.3, 0.2) facing east and the planner finds a route
to (0.95, 0.2). Then x1 (the injected block) lands across that route at (0.62, 0.2). Perception hears only
that a change happened. Its LiDAR now stops at x1's west face, so x1 itself and everything behind it can no
longer be seen. The planner must not keep trusting those old free cells: it asks for a re-look and publishes
nothing. Once the Scout looks again from the south-east, the planner finds a new route that goes round x1.
Block poses are used only by the test world, to move x1 and to score the route, never by perception.
"""

import asyncio

import mujoco
import pytest

import perception.grid as grid_module
from perception.grid import cell_of
from perception.tests.closed_loop import Loop, footprint
from planner.route import RoutePlanner

SCOUT = (0.3, 0.2)             # where the Scout maps room 2 from, facing east
GOAL_XY = (0.95, 0.2)          # behind where x1 lands
X1_AT = (0.62, 0.2, 0.08)      # x1 is 0.2 x 0.2 x 0.16 m
SIDE = (0.9, -0.6, 1.57)       # the re-look: south-east of x1, facing north


class Bus:
    def __init__(self):
        self.published = []

    def subscribe(self, topic, callback):
        pass

    async def publish(self, topic, data):
        self.published.append((topic, data))


def ground(xy):
    i, j, _ = cell_of((xy[0], xy[1], 0.0))
    return (i, j, 0)


def propose(planner):
    return asyncio.run(planner.propose(ground(SCOUT), ground(GOAL_XY)))


def drop_x1(loop):
    """The test world puts x1 on the route; perception is told only that something changed."""
    adr = loop.m.joint(loop.m.body("x1").jntadr[0]).qposadr[0]
    loop.d.qpos[adr:adr + 7] = [*X1_AT, 1, 0, 0, 0]
    mujoco.mj_forward(loop.m, loop.d)
    loop.hazards.on_change({"kind": "inject", "t": loop.t, "moved_blocks": ["x1"]}, loop.t)


def run():
    """Map, plan, shift, plan again. Returns the loop, planner, bus and the two results."""
    loop = Loop(start=SCOUT, depth=False)
    bus = Bus()
    planner = RoutePlanner(bus)
    loop.watch(*SCOUT, 0.0, 30)
    planner.update_map(loop.grid.snapshot(loop.t))
    planner.update_hazards(loop.hazards.message())
    before = propose(planner)
    drop_x1(loop)
    loop.watch(*SCOUT, 0.0, 10)
    planner.update_map(loop.grid.delta(loop.t))          # only changed cells; forgotten ones say unknown
    planner.update_hazards(loop.hazards.message())
    after = propose(planner)
    return loop, planner, bus, before, after


def x1_cells(loop):
    return {(i, j) for i, j in footprint(loop.m, loop.d, "x1")}


def test_debris_on_the_route_makes_the_planner_ask_for_a_re_look():
    loop, _, bus, before, after = run()
    assert before["status"] == "ok"
    assert {tuple(c[:2]) for c in before["cells"]} & x1_cells(loop), "the first route runs where x1 lands"
    assert len(bus.published) == 1
    assert after["status"] == "no_verified_route" and after["needs"] == "re-look"
    assert after["cells"], "the planner names frontier cells to re-look at"
    assert len(bus.published) == 1, "a failed search publishes no route/proposed"
    assert loop.grid.column(*ground(GOAL_XY)[:2]) == ("unknown", False)   # x1 hides the goal now


def test_after_a_fresh_look_the_new_route_goes_round_the_debris():
    loop, planner, bus, before, _ = run()
    loop.watch(*SIDE, 10)
    planner.update_map(loop.grid.delta(loop.t))
    planner.update_hazards(loop.hazards.message())
    again = propose(planner)
    assert again["status"] == "ok"
    cells = {tuple(c[:2]) for c in again["cells"]}
    assert not cells & x1_cells(loop), "the new route never crosses x1"
    assert again["cells"] != before["cells"]
    assert bus.published[-1][0] == "route/proposed" and bus.published[-1][1]["id"] == "r2"


def test_without_forgetting_the_shadow_the_planner_trusts_stale_cells(monkeypatch):
    """Why #209 matters: with the shadow step off, x1's own cells stay free in the map and the planner
    claims a verified route to a goal no ray has reached since the change."""
    monkeypatch.setattr(grid_module, "SHADOW", 0.0)
    loop, _, _, _, after = run()
    assert after["status"] == "ok"
    stale = [ij for ij in x1_cells(loop) if loop.grid.column(*ij) == ("seen", False)]
    assert stale, "x1's inside is still mapped free"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
