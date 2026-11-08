"""Tests for voice first aid guidance (T22).

Validates:
1. voice/firstaid.json contains between 5 and 8 short steps.
2. Every step has a valid, non-empty source URL from an authoritative first aid body.
3. The steps guide a human and do not perform medical diagnosis.
4. Helper functions format CONTRACT-compliant 'say' messages.
"""

from urllib.parse import urlparse

import pytest

from voice import firstaid


def test_firstaid_step_count():
    steps = firstaid.get_steps()
    assert 5 <= len(steps) <= 8, f"Expected 5 to 8 first aid steps, got {len(steps)}"


def test_every_step_has_valid_source():
    steps = firstaid.get_steps()
    for step in steps:
        step_id = step.get("id")
        source = step.get("source")
        assert source, f"Step {step_id} is missing a source URL"
        assert isinstance(source, str), f"Step {step_id} source must be a string"

        parsed = urlparse(source)
        assert parsed.scheme in ("http", "https"), f"Step {step_id} has invalid scheme: {source}"
        assert parsed.netloc, f"Step {step_id} has empty domain: {source}"
        # Verify source is from an authoritative healthcare or first aid organisation
        assert any(
            domain in parsed.netloc.lower()
            for domain in ("redcross", "nhs.uk", "sja.org.uk")
        ), f"Step {step_id} source not from a recognized first aid body: {source}"


def test_core_actions_present():
    steps = firstaid.get_steps()
    actions = {step.get("action") for step in steps}
    expected_actions = {"check_breathing", "control_bleeding", "protect_spine", "keep_warm"}
    assert expected_actions.issubset(actions), f"Missing required actions: {expected_actions - actions}"


def test_casualty_lines_are_short_and_only_on_self_care_steps():
    """ref FIRSTAID-SOURCES: steps for a bystander (check breathing, recovery position) are never said to the
    trapped casualty; every casualty_line is short and plain."""
    lines = {s["action"]: s.get("casualty_line") for s in firstaid.get_steps()}
    assert lines["check_breathing"] is None and lines["recovery_position"] is None
    for action in ("control_bleeding", "protect_spine", "keep_limb_still", "protect_airway_from_dust", "keep_warm"):
        line = firstaid.casualty_line(action)
        assert 0 < len(line.split()) <= 20, action
    with pytest.raises(ValueError):
        firstaid.casualty_line("check_breathing")


def test_disclaimer_present():
    data = firstaid.load_firstaid_data()
    assert "disclaimer" in data
    assert "diagnosis" in data["disclaimer"].lower() or "guidance" in data["disclaimer"].lower()


def test_get_step_by_id_and_action():
    step_by_id = firstaid.get_step("step_1")
    assert step_by_id is not None
    assert step_by_id["action"] == "check_breathing"

    step_by_action = firstaid.get_step("control_bleeding")
    assert step_by_action is not None
    assert step_by_action["id"] == "step_2"

    assert firstaid.get_step("non_existent_action") is None


def test_format_guidance():
    step = firstaid.get_step("step_1")
    text = firstaid.format_guidance(step)
    assert "Check Breathing" in text
    assert "10 seconds" in text


def _check_say(payload):
    try:
        from coord.messages import TOPICS
        TOPICS["say"].model_validate(payload)
    except (ImportError, KeyError):
        assert set(payload.keys()) >= {"to", "intent", "text", "lang"}
        assert payload["to"] in ("casualty", "operator")
        assert payload["intent"] in ("first_aid", "guide_exit", "reassure")
        assert isinstance(payload["text"], str)


def test_create_say_message():
    say = firstaid.create_say_message("check_breathing", to="casualty")
    assert say["to"] == "casualty"
    assert say["intent"] == "first_aid"
    assert "Check Breathing" in say["text"]
    assert say["lang"] == "auto"
    _check_say(say)

    with pytest.raises(ValueError):
        firstaid.create_say_message("invalid_step_name")
