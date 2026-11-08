"""DOUBLE-SHIFT: two real scene changes each revoke a route until a fresh scan."""

import asyncio

import pytest

pytest.importorskip("mujoco")

from planner import loop as L
from planner.tests.test_loop import setup, two_gap_map, verify
from sim.world import World
from tools.tests.test_shift_recheck import AT_RISK, corridor_explorer


def world_change(world, kind):
    if kind == "aftershock":
        assert world.trigger_aftershock()
    else:
        assert world.add_block([-0.9, 0.25, 0.3]) == "x1"
    for _ in range(50):
        changes = [data for topic, data in world.tick(0.1) if topic == "world/change"]
        if changes:
            assert len(changes) == 1 and changes[0]["kind"] == kind
            return changes[0]
    pytest.fail(f"{kind} never appeared in the real simulation")


def test_two_slabs_each_stop_and_require_their_own_new_scan():
    world = World(render=False)
    bus, planner, clock = setup()
    verify(bus, "r1", True)
    assert planner.state == L.EXECUTING
    scout = corridor_explorer()
    scout.on_hazards(AT_RISK)
    bus.subscribe("world/change", scout.on_change)

    for kind, moved in (("aftershock", "b10"), ("block_added", "x1")):
        old_route = planner.route["id"]
        actions_before = len(bus.of("responder/action"))
        proposals_before = len(bus.of("route/proposed"))
        change = world_change(world, kind)
        assert moved in change["moved_blocks"]
        clock.now = change["t"]
        asyncio.run(bus.publish("world/change", change))
        assert planner.state == L.IDLE and planner.route is None and planner.waiting_scan
        assert len(bus.of("responder/action")) == actions_before
        assert len(bus.of("route/proposed")) == proposals_before
        assert scout.tick(change["t"] + 0.1)["reason"].startswith("re-scan after the")

        # The old verification cannot release the hold. Only the next measured map can propose a route.
        verify(bus, old_route, True)
        assert planner.route is None and len(bus.of("responder/action")) == actions_before
        clock.now += 0.5
        asyncio.run(bus.publish("map/cells", two_gap_map()))
        proposals = bus.of("route/proposed")[proposals_before:]
        assert len(proposals) == 1 and proposals[0]["id"] != old_route
        assert len(bus.of("responder/action")) == actions_before
        verify(bus, proposals[0]["id"], True)
        assert planner.state == L.EXECUTING
