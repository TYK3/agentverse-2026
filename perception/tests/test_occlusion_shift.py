"""OCCLUSION-SHIFT (ref #31/#144, after #209): debris lands on a mapped route while the Scout cannot see it.

The backup scene. The Scout maps room 2 from (0.3, 0.2) facing east, and the planner finds a route to
(0.95, 0.2). The Scout then goes to (-0.7, -0.5) in room 1, where the wall hides room 2 from its LiDAR
(no ray reaches x1 there), and x1 (the injected block) lands across the route at (0.62, 0.2).
Perception hears only that a change happened, as in a real aftershock.

- Hidden: perception makes nothing up. With no ray reaching x1, no cell has `appeared` and x1's cells
  read as they were last measured.
- Back in view: x1's west face appears, the cells it hides are forgotten (#209), and the planner asks
  for a re-look instead of trusting the old route.
- After a look from the south-east, the new route goes round x1.
- Known gap (strict xfail): while the Scout is hidden, the planner still plans "ok" through x1 on cells
  measured before the change. Neither perception nor the planner on main marks a pre-change cell as
  unconfirmed. The planner's G4 guard (#212: route cells need post-change measurements) targets it.
  When that lands, this test passes, strict xfail turns it red, and the marker should go.
Block poses are used only by the test world, to move x1 and to score the route, never by perception.
"""

import asyncio

import mujoco
import pytest

from perception.grid import cell_of
from perception.tests.closed_loop import Loop, footprint
from planner.route import RoutePlanner

SCOUT = (0.3, 0.2)             # maps room 2 from here, facing east
GOAL_XY = (0.95, 0.2)          # behind where x1 lands
HIDE = (-0.7, -0.5)            # in room 1: the wall hides x1 from every LiDAR ray
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


class World:
    """The closed loop plus the planner, fed map/cells deltas and map/hazards as on the bus."""

    def __init__(self):
        self.loop = Loop(start=SCOUT, depth=False)
        self.bus = Bus()
        self.planner = RoutePlanner(self.bus)
        self.loop.watch(*SCOUT, 0.0, 30)
        self.first = self.plan(snapshot=True)

    def plan(self, snapshot=False):
        grid = self.loop.grid
        self.planner.update_map(grid.snapshot(self.loop.t) if snapshot else grid.delta(self.loop.t))
        self.planner.update_hazards(self.loop.hazards.message())
        return asyncio.run(self.planner.propose(ground(SCOUT), ground(GOAL_XY)))

    def hide_and_drop_x1(self):
        loop = self.loop
        loop.watch(*HIDE, 0.0, 10)
        adr = loop.m.joint(loop.m.body("x1").jntadr[0]).qposadr[0]
        loop.d.qpos[adr:adr + 7] = [*X1_AT, 1, 0, 0, 0]
        mujoco.mj_forward(loop.m, loop.d)
        change = {"kind": "inject", "t": loop.t, "moved_blocks": ["x1"]}
        loop.hazards.on_change(change, loop.t)
        loop.explorer.on_change(change)
        loop.watch(*HIDE, 0.0, 10)

    def x1_cells(self):
        return footprint(self.loop.m, self.loop.d, "x1")

    def crosses_x1(self, result):
        return bool({tuple(c[:2]) for c in result["cells"]} & self.x1_cells())


@pytest.fixture
def world():
    w = World()
    assert w.first["status"] == "ok"
    w.hide_and_drop_x1()
    assert w.crosses_x1(w.first), "the first route runs where x1 lands"
    return w


def test_out_of_sight_perception_makes_nothing_up(world):
    grid = world.loop.grid
    assert not grid.appeared, "no ray reached x1, so nothing may appear"
    assert {grid.column(*ij) for ij in world.x1_cells()} == {("seen", False)}, "as last measured"


def test_back_in_view_the_planner_asks_for_a_re_look(world):
    world.plan()
    world.loop.watch(*SCOUT, 0.0, 10)
    grid = world.loop.grid
    assert grid.appeared, "x1's west face is sensed"
    assert any(grid.column(*ij) == ("seen", True) for ij in world.x1_cells())
    assert grid.column(*ground(GOAL_XY)[:2]) == ("unknown", False), "x1 hides the goal now (#209)"
    again = world.plan()
    assert again["status"] == "no_verified_route" and again["needs"] == "re-look"


def test_after_a_side_look_the_route_goes_round_x1(world):
    world.plan()
    world.loop.watch(*SCOUT, 0.0, 10)
    world.plan()
    world.loop.watch(*SIDE, 10)
    route = world.plan()
    assert route["status"] == "ok"
    assert not world.crosses_x1(route), "the new route never crosses x1"
    assert world.bus.published[-1][0] == "route/proposed"


@pytest.mark.xfail(strict=True, reason="known gap: pre-change cells are trusted while the Scout is out of "
                   "sight; planner G4 guard #212 targets it")
def test_out_of_sight_the_planner_does_not_trust_pre_change_cells(world):
    hidden = world.plan()
    assert hidden["status"] != "ok" or not world.crosses_x1(hidden)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
