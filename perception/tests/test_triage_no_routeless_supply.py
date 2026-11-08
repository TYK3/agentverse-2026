"""Triage approval cannot drop the Responder's load before routed delivery."""

import asyncio

import pytest

from coord import gem
from coord.hub import Bus
from perception.triage import TriageAssessment, Triager


@pytest.fixture(autouse=True)
def gemini_off(monkeypatch):
    monkeypatch.setenv("GEMINI_MODE", "off")
    monkeypatch.setattr(gem, "MODE", "off")


def assessment(route="none"):
    return TriageAssessment(
        casualty_id="c1", triage_level="delayed", confidence=0.65,
        injuries=[], hurt_parts=[], recommended_item="water", options=[],
        needs_human=True, rationale="Operator chooses supply, planner routes it",
        gate_request_id="g_triage_c1", route=route,
    )


@pytest.mark.parametrize("route", ["none", None, "", "   ", "None"])
def test_approved_triage_without_route_cannot_dispatch_placement(route):
    async def scenario():
        bus = Bus()
        actions, decisions = [], []
        bus.subscribe("responder/action", actions.append)
        bus.subscribe("log/decision", decisions.append)
        triager = Triager().attach(bus)
        triager.pending_gates["g_triage_c1"] = assessment(route)

        await bus.publish("gate/answer", {"id": "g_triage_c1", "approved": True, "by": "operator"})

        assert actions == [], "triage approval alone must not queue or drop a supply"
        assert "g_triage_c1" not in triager.pending_gates
        assert decisions[-1]["outcome"] == "approved"
        assert "route" in decisions[-1]["reason"]

    asyncio.run(scenario())


def test_high_confidence_triage_without_route_leaves_placement_to_planner():
    async def scenario():
        bus = Bus()
        actions, recommendations = [], []
        bus.subscribe("responder/action", actions.append)
        bus.subscribe("casualty/triage", recommendations.append)
        triager = Triager(dialogue_reader=lambda cid: {
            "casualty": cid,
            "answers": {"bleeding": "yes", "hurt": "yes", "breathing": "no", "move": "yes", "walk": "yes"},
        }).attach(bus)

        events = await triager.on_casualties([{
            "id": "c1", "pos": [2, 1, 0.075], "confidence": 0.95,
            "clues": ["thermal", "sound", "camera"],
        }])

        assert recommendations[-1]["recommended_action"] == "bandage"
        assert triager.assessments["c1"].needs_human is False
        assert actions == [], "a confident recommendation still has no delivery route"
        assert not any(topic == "responder/action" for topic, _ in events)

    asyncio.run(scenario())


def test_approved_triage_with_explicit_route_preserves_routed_action():
    async def scenario():
        bus = Bus()
        actions = []
        bus.subscribe("responder/action", actions.append)
        triager = Triager().attach(bus)
        triager.pending_gates["g_triage_c1"] = assessment("r-approved")

        await bus.publish("gate/answer", {"id": "g_triage_c1", "approved": True, "by": "operator"})

        assert actions == [{"action": "place_supply", "route": "r-approved", "item": "water"}]

    asyncio.run(scenario())
