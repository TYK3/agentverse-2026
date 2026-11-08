"""GATE-ORDER (#52): an approved gate/answer reaches the sim's Responder before the planner dispatches.

The hub runs a topic's callbacks in subscription order and awaits each one. If the planner's
gate/answer callback runs first, it publishes responder/action move before the sim's Responder has
recorded the approval, and the sim refuses the risky route (seen in run_rescue seed 6). The planner
must not depend on which lane started first.
"""

import asyncio

from planner import loop as L
from planner.tests.test_loop import CASUALTY, Bus, setup, verify


class SimGate:
    """The part of sim/responder.py that matters here: risky routes need an approved gate/answer."""

    def __init__(self, bus):
        self.risky, self.approved, self.moves = {}, set(), []
        bus.subscribe("gate/request", self.on_request)
        bus.subscribe("gate/answer", self.on_answer)
        bus.subscribe("responder/action", self.on_action)

    def on_request(self, msg):
        self.risky[msg["id"]] = msg["route"]

    def on_answer(self, msg):
        if msg.get("approved") is True and msg.get("id") in self.risky:
            self.approved.add(self.risky[msg["id"]])

    def on_action(self, msg):
        if msg["action"] == "move":
            self.moves.append((msg["route"], msg["route"] in self.approved))


def test_sim_records_approval_before_the_planner_moves_even_when_the_planner_started_first():
    bus, lp, _ = setup(casualty={**CASUALTY, "confidence": 0.3})  # planner subscribed first
    sim = SimGate(bus)                                           # sim lane started after it
    verify(bus, "r1", True)
    req = bus.of("gate/request")[-1]
    assert req["kind"] == "risky_move"
    asyncio.run(bus.publish("gate/answer", {"id": req["id"], "approved": True, "by": "operator"}))
    assert sim.moves == [("r1", True)]
    assert lp.state == L.EXECUTING


def test_one_answer_is_handled_once_across_many_requests():
    bus, lp, _ = setup(casualty={**CASUALTY, "confidence": 0.3})
    verify(bus, "r1", True)
    first = bus.of("gate/request")[-1]
    asyncio.run(bus.publish("gate/answer", {"id": first["id"], "approved": False, "by": "operator"}))
    verify(bus, "r1", True)  # a second request on the same loop
    assert bus.subs["gate/answer"].count(lp.on_answer) == 1


def test_no_request_means_the_planner_ignores_answers():
    bus = Bus()
    from planner.route import RoutePlanner
    lp = L.Loop(bus, RoutePlanner(bus), gem=None).attach()
    asyncio.run(bus.publish("gate/answer", {"id": "g1", "approved": True, "by": "operator"}))
    assert not bus.of("responder/action") and lp.request is None
