"""A Responder stopped by its collision ray (sim/responder.py "blocked") drops its queued
place_supply/release; the planner must leave EXECUTING and propose a new route on the next map."""

import asyncio

from planner import loop as L
from planner.tests.test_loop import setup, two_gap_map, verify


def blocked(rid, t=12.0):
    return {"t": t, "perception": "responder at [0.2, 0.3]", "model": "sim", "physics": "mujoco",
            "outcome": "blocked", "reason": f"collision ray: block ahead on route {rid}, stopped, "
                                            "dropped 2 queued action(s)"}


def test_blocked_while_executing_replans_on_next_map():
    bus, lp, clock = setup()
    verify(bus, "r1", True)
    assert lp.state == L.EXECUTING
    asyncio.run(bus.publish("log/decision", blocked("r1")))
    assert lp.state == L.IDLE and lp.route is None
    assert bus.of("log/decision")[-1]["outcome"] == "replanning"
    n = len(bus.of("route/proposed"))
    clock.now = 2.0
    asyncio.run(bus.publish("map/cells", two_gap_map()))
    new = bus.of("route/proposed")[n:]
    assert len(new) == 1 and new[0]["id"] != "r1"
    assert any("map re-scanned after Responder blocked on r1" in d["perception"] for d in bus.of("log/decision"))


def test_stale_or_repeated_block_is_ignored():
    bus, lp, _ = setup()
    verify(bus, "r1", True)
    asyncio.run(bus.publish("log/decision", blocked("r9")))      # not the executing route
    asyncio.run(bus.publish("log/decision", blocked("r10")))     # "r1" must not match "r10"
    assert lp.state == L.EXECUTING
    asyncio.run(bus.publish("log/decision", blocked("r1")))
    k = len(bus.sent)
    asyncio.run(bus.publish("log/decision", blocked("r1")))      # repeat: already IDLE
    assert lp.state == L.IDLE and len(bus.sent) == k + 1


def test_blocked_replans_from_the_responder_cell():
    bus, lp, clock = setup()
    lp.start_cell = lambda: (2, 3, 0)
    verify(bus, "r1", True)
    asyncio.run(bus.publish("log/decision", blocked("r1")))
    n = len(bus.of("route/proposed"))
    clock.now = 2.0
    asyncio.run(bus.publish("map/cells", two_gap_map()))
    assert bus.of("route/proposed")[n]["cells"][0] == [2, 3, 0]
