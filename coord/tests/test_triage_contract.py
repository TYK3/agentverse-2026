"""The accepted Y3 supply choice crosses the real hub; it grants no physical permission."""

import asyncio
import json
from pathlib import Path

import pytest

from coord.hub import BROWSER_TOPICS, Bus
from coord.messages import validate_payload


@pytest.mark.parametrize("item", ["water", "first_aid_kit", "radio", "bandage", "splint", "thermal_blanket"])
def test_accepted_supply_choice_is_registered(item):
    payload = {"id": "c1", "injuries": [], "recommended_action": item}
    assert validate_payload("casualty/triage", payload) == payload


@pytest.mark.parametrize("change", [{"recommended_action": "unknown"}, {"route": "r1"}, {"id": ""}])
def test_invalid_or_physical_triage_fields_are_rejected(change):
    with pytest.raises(ValueError):
        validate_payload("casualty/triage", {"id": "c1", "injuries": [], "recommended_action": "water", **change})


def test_fixture_reaches_planner_subscriber_without_dispatching_actions():
    fixture = json.loads((Path(__file__).parents[1] / "fixtures" / "casualty__triage.json").read_text(encoding="utf-8"))
    bus, received = Bus(), []
    bus.subscribe("casualty/triage", received.append)
    asyncio.run(bus.publish(fixture["topic"], fixture["data"]))
    assert received == [fixture["data"]]
    assert [m["topic"] for m in bus.history] == ["casualty/triage"]
    assert "casualty/triage" not in BROWSER_TOPICS
