"""Approval boundaries, expiry and ordered Responder dispatch (T14)."""

import asyncio

import pytest

from planner import loop as L
from planner.tests.test_loop import (
    CASUALTY,
    GOAL,
    START,
    Bus,
    Clock,
    OffGem,
    two_gap_map,
)


async def mission(*, confidence=0.9, action="deliver", timeout=60, clock=None):
    bus = Bus()
    lp = await L.start(bus, gem=OffGem(), budget=False, gate_timeout=timeout, **({"clock": clock} if clock else {}))
    await bus.publish("map/cells", two_gap_map())
    await bus.publish("map/casualties", [{**CASUALTY, "confidence": confidence}])
    await lp.mission(START, GOAL, action=action)
    return bus, lp


async def verify(bus, lp, ok=True):
    await bus.publish("route/verified", {
        "id": lp.route["id"], "ok": ok, "unstable_cells": [], "detail": "fixture physics",
    })


async def answer(bus, request, approved=True):
    await bus.publish("gate/answer", {"id": request["id"], "approved": approved, "by": "operator"})


def test_safe_delivery_dispatches_move_supply_release_after_verification():
    async def scenario():
        bus, lp = await mission()
        assert not bus.of("responder/action")
        await verify(bus, lp)
        assert not bus.of("gate/request")
        assert [a["action"] for a in bus.of("responder/action")] == ["move", "place_supply", "release"]
        assert all(a["item"] == "water" and a["route"] == "r1" for a in bus.of("responder/action"))
    asyncio.run(scenario())


@pytest.mark.parametrize("risk", ["grip", "at_risk", "confidence"])
def test_risky_task_waits_for_its_own_approval_and_consumes_it_once(risk):
    async def scenario():
        bus, lp = await mission(action="grip" if risk == "grip" else "deliver",
                                confidence=0.3 if risk == "confidence" else 0.9)
        if risk == "at_risk":
            await bus.publish("map/hazards", [{"cell": lp.route["cells"][2], "status": "at_risk",
                                               "why": "new estimate", "estimate": True}])
        await verify(bus, lp)
        request = bus.of("gate/request")[-1]
        assert request["kind"] == ("enter_at_risk" if risk == "at_risk" else "risky_move")
        assert not bus.of("responder/action")
        await answer(bus, {"id": "g999"})
        assert not bus.of("responder/action") and lp.request
        await answer(bus, request)
        expected = ["move", "grip", "place_supply", "release"] if risk == "grip" else [
            "move", "place_supply", "release"]
        assert [a["action"] for a in bus.of("responder/action")] == expected
        await answer(bus, request)
        assert len(bus.of("responder/action")) == len(expected)
        assert lp.request is None
    asyncio.run(scenario())


@pytest.mark.parametrize("approved", [False, "true", 1, None])
def test_only_literal_approval_unlocks_risky_work(approved):
    async def scenario():
        bus, lp = await mission(action="grip")
        await verify(bus, lp)
        await lp.on_answer({"id": lp.request["id"], "approved": approved})
        assert not bus.of("responder/action") and lp.state == L.IDLE
        assert "refused" in bus.of("log/decision")[-1]["reason"]
    asyncio.run(scenario())


def test_default_deadline_is_60_seconds_and_late_approval_is_refused():
    async def scenario():
        clock = Clock()
        bus, lp = await mission(action="grip", clock=clock)
        await verify(bus, lp)
        request = dict(lp.request)
        clock.now = 60.0
        await answer(bus, request)
        assert not bus.of("responder/action") and lp.state == L.IDLE
        assert "timeout: refused" in bus.of("log/decision")[-1]["reason"]
    asyncio.run(scenario())


def test_timeout_fires_without_an_answer_and_late_answers_cannot_revive_it():
    async def scenario():
        bus, lp = await mission(action="grip", timeout=0.01)
        await verify(bus, lp)
        request = dict(lp.request)
        await asyncio.sleep(0.04)
        assert lp.request is None and lp.state == L.IDLE
        assert "timeout: refused" in bus.of("log/decision")[-1]["reason"]
        await answer(bus, request)
        assert not bus.of("responder/action")
    asyncio.run(scenario())


def test_immediate_answer_from_console_during_request_publication_works():
    async def scenario():
        bus, lp = await mission(action="grip")

        async def approve(request):
            await answer(bus, request)

        bus.subscribe("gate/request", approve)
        await verify(bus, lp)
        assert len(bus.of("responder/action")) == 4
        assert lp.request is None and lp._gate_timer is None
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["aftershock", "new_mission"])
def test_old_request_cannot_authorise_a_replacement_route(change):
    async def scenario():
        bus, lp = await mission(action="grip")
        await verify(bus, lp)
        request = dict(lp.request)
        if change == "aftershock":
            await bus.publish("world/change", {"kind": "aftershock", "t": 1, "moved_blocks": ["b7"]})
        else:
            await lp.mission(START, GOAL, action="grip")
        await answer(bus, request)
        assert not bus.of("responder/action")
        assert any("cancelled" in log["reason"] for log in bus.of("log/decision"))
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["unknown", "occupied", "collapsed"])
def test_approval_cannot_override_newly_unsafe_cells(change):
    async def scenario():
        bus, lp = await mission(action="grip")
        await verify(bus, lp)
        request, cell = dict(lp.request), lp.route["cells"][2]
        if change == "collapsed":
            await bus.publish("map/hazards", [{"cell": cell, "status": "collapsed",
                                               "why": "moved rubble", "estimate": True}])
        else:
            await bus.publish("map/cells", {"t": 1, "res": 0.1, "cells": [
                {"cell": cell, "state": "unknown" if change == "unknown" else "seen",
                 "occupied": change == "occupied"}]})
        await answer(bus, request)
        assert not bus.of("responder/action") and lp.state == L.IDLE
        assert "Responder idle" in bus.of("log/decision")[-1]["reason"]
    asyncio.run(scenario())


def test_new_at_risk_cell_requires_a_new_approval_kind():
    async def scenario():
        bus, lp = await mission(action="grip")
        await verify(bus, lp)
        request = dict(lp.request)
        await bus.publish("map/hazards", [{"cell": lp.route["cells"][2], "status": "at_risk",
                                           "why": "new risk", "estimate": True}])
        await answer(bus, request)
        assert not bus.of("responder/action")
        assert lp.request["id"] != request["id"] and lp.request["kind"] == "enter_at_risk"
        await answer(bus, lp.request)
        assert len(bus.of("responder/action")) == 4
    asyncio.run(scenario())


def test_human_approval_cannot_override_failed_physics():
    async def scenario():
        bus, lp = await mission()
        for _ in range(4):
            await verify(bus, lp, ok=False)
        assert lp.request
        await answer(bus, lp.request)
        assert not bus.of("responder/action") and lp.state == L.IDLE
        assert "physics verification" in bus.of("log/decision")[-1]["reason"]
    asyncio.run(scenario())


@pytest.mark.parametrize("approved", [True, False])
def test_emergency_message_is_displayed_but_never_executes_robot_actions(approved):
    async def scenario():
        bus = Bus()
        lp = await L.start(bus, gem=OffGem(), budget=False)
        request = await lp.prepare_emergency_call("Casualty c1 at the back room, rescue needed")
        assert request["kind"] == "emergency_call" and request["route"] == "none"
        assert "back room" in bus.of("gate/request")[-1]["summary"]
        await answer(bus, request, approved)
        assert not bus.of("responder/action") and lp.state == L.IDLE
        log = bus.of("log/decision")[-1]
        assert log["outcome"] == ("prepared" if approved else "hold")
        if approved:
            assert "no call placed" in log["reason"]
    asyncio.run(scenario())


def test_aftershock_during_dispatch_cancels_the_remaining_commands():
    async def scenario():
        bus, lp = await mission()

        async def after_move(action):
            if action["action"] == "move":
                await bus.publish("world/change", {"kind": "aftershock", "t": 1, "moved_blocks": ["b7"]})

        bus.subscribe("responder/action", after_move)
        await verify(bus, lp)
        assert [a["action"] for a in bus.of("responder/action")] == ["move"]
        assert lp.state == L.IDLE
    asyncio.run(scenario())


def test_synchronous_physics_response_is_not_lost():
    async def scenario():
        bus = Bus()

        async def physics(route):
            await bus.publish("route/verified", {"id": route["id"], "ok": True,
                                                 "unstable_cells": [], "detail": "fixture"})

        bus.subscribe("route/proposed", physics)
        lp = await L.start(bus, gem=OffGem(), budget=False)
        await bus.publish("map/cells", two_gap_map())
        await bus.publish("map/casualties", [CASUALTY])
        await lp.mission(START, GOAL, action="grip")
        assert lp.request and lp.verified_route == "r1"
        assert not bus.of("responder/action")
        await answer(bus, lp.request)
        assert len(bus.of("responder/action")) == 4
    asyncio.run(scenario())


def test_route_replacement_during_approval_log_cannot_reuse_old_permission():
    async def scenario():
        bus, lp = await mission(action="grip")
        await verify(bus, lp)
        request = dict(lp.request)

        async def replace(log):
            if log["perception"] == f"operator approved {request['id']}":
                await lp.mission(START, GOAL, action="grip")
                await verify(bus, lp)

        bus.subscribe("log/decision", replace)
        await answer(bus, request)
        assert not bus.of("responder/action")
        assert lp.request and lp.request["route"] == "r2"
    asyncio.run(scenario())


def test_hub_bus_accepts_the_gate_and_ordered_action_payloads():
    from coord import hub

    async def scenario():
        bus = hub.Bus()

        async def physics(route):
            await bus.publish("route/verified", {"id": route["id"], "ok": True,
                                                 "unstable_cells": [], "detail": "fixture"})

        bus.subscribe("route/proposed", physics)
        lp = await L.start(bus, gem=OffGem(), budget=False)
        await bus.publish("map/cells", two_gap_map())
        await bus.publish("map/casualties", [CASUALTY])
        await lp.mission(START, GOAL, action="grip")
        assert lp.request and not any(m["topic"] == "responder/action" for m in bus.history)
        await bus.publish("gate/answer", {"id": lp.request["id"], "approved": True, "by": "operator"})
        assert [m["data"]["action"] for m in bus.history if m["topic"] == "responder/action"] == [
            "move", "grip", "place_supply", "release"]
    asyncio.run(scenario())


@pytest.mark.parametrize("command", ["stop", "hold"])
def test_stop_cancels_pending_approval_without_requiring_place_configuration(command):
    async def scenario():
        bus, lp = await mission(action="grip")
        await verify(bus, lp)
        request = dict(lp.request)
        await lp.on_command({"text": command, "source": "typed"})
        assert lp.request is None and lp._gate_timer is None and lp.state == L.IDLE
        await answer(bus, request)
        assert not bus.of("responder/action")
    asyncio.run(scenario())
