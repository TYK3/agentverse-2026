"""A nested physics verdict must reach permits in either lane subscription order."""

import asyncio
import inspect

import pytest

from planner import permit

ROUTE = {"id": "r1", "robot": "responder", "cells": [[10, 10, 0], [11, 10, 0]],
         "goal": "deliver water", "model": "local-astar"}


class Bus:
    def __init__(self):
        self.subs = {}
        self.sent = []

    def subscribe(self, topic, callback):
        self.subs.setdefault(topic, []).append(callback)

    async def publish(self, topic, data):
        self.sent.append((topic, data))
        for callback in tuple(self.subs.get(topic, ())):
            result = callback(data)
            if inspect.isawaitable(result):
                await result


@pytest.mark.parametrize("sim_first", [True, False])
@pytest.mark.parametrize("physics_ok", [True, False])
def test_nested_route_verification_is_processed_in_both_lane_orders(sim_first, physics_ok):
    async def scenario():
        bus = Bus()

        async def physics(route):
            await bus.publish("route/verified", {"id": route["id"], "ok": physics_ok,
                                                 "unstable_cells": [], "detail": ""})

        if sim_first:
            bus.subscribe("route/proposed", physics)
        permits = permit.start(bus, clock=lambda: 1.0)
        if not sim_first:
            bus.subscribe("route/proposed", physics)
        await bus.publish("route/proposed", ROUTE)
        return bus, permits

    bus, permits = asyncio.run(scenario())
    decisions = [data for topic, data in bus.sent if topic == "permit/route"]
    assert len(decisions) == 1
    assert decisions[0]["route"] == "r1"
    assert decisions[0]["granted"] is physics_ok
    assert permits.granted("r1") is physics_ok


def test_orphan_verification_never_grants_a_route():
    async def scenario():
        bus = Bus()
        permits = permit.start(bus, clock=lambda: 1.0)
        await bus.publish("route/verified", {"id": "r1", "ok": True, "unstable_cells": [], "detail": ""})
        return bus, permits

    bus, permits = asyncio.run(scenario())
    assert not permits.granted("r1")
    assert all(topic != "permit/route" for topic, _ in bus.sent)
