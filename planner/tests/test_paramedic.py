"""Y6 report isolation, truthful provenance, missing observations and optional dialogue."""

import asyncio
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from planner.paramedic import ParamedicReports, guide_summary, is_report_command


def casualty(cid="c1", **extra):
    return {"id": cid, "pos": [1, 2, 0], "confidence": 0.8, "clues": ["thermal", "sound"],
            "vitals": {"breathing_rate": 14, "simulated": True}, **extra}


def facts():
    return {"routes": [{"id": "r1", "goal": "deliver water to c1"},
                       {"id": "r10", "goal": "deliver water to c10"}],
            "actions": [{"route": "r1", "action": "place_supply", "item": "water", "t": 3,
                         "status": "commanded; completion unconfirmed"},
                        {"route": "r10", "action": "place_supply", "item": "water", "t": 4,
                         "status": "simulated placement confirmed by sim log"}],
            "supplies_delivered": [{"item": "water", "route": "r10", "pos": [3, 4], "t": 5, "simulated": True},
                                   {"item": "radio", "route": None, "pos": [9, 9], "t": 6, "simulated": True}],
            "approvals": [{"id": "g10", "route": "r10", "status": "operator denied", "answers": []}]}


def test_per_casualty_actions_and_approvals_never_match_c1_to_c10():
    store = ParamedicReports(lambda: 2, dialogue_summary=lambda _: None)
    store.observe([casualty(), casualty("c10")])
    one, ten = store.build(facts())
    assert [a["route"] for a in one["actions"]] == ["r1"]
    assert one["supplies_delivered"] == [] and one["approvals"] == []
    assert [d["route"] for d in ten["supplies_delivered"]] == ["r10"]
    assert ten["approvals"][0]["status"] == "operator denied"
    assert any("unconfirmed" in text for text in one["unknowns"])


def test_optional_dialogue_is_allowlisted_and_missing_answers_stay_unknown():
    dialogue = {"casualty": "c1", "answers": {"hear": "yes", "hurt": "yes", "bleeding": "unsure"},
                "hurt_parts": ["arm", "arm", "PRIVATE_NAME"], "face": "PRIVATE_IMAGE_BYTES",
                "diagnosis": "invented", "can_walk": True}
    store = ParamedicReports(lambda: 2, dialogue_summary=lambda _: dialogue)
    store.observe([casualty()])
    report = store.build(facts())[0]
    assert report["injuries"] == {"status": "reported", "hurt_parts": ["arm"],
                                   "source": "self_reported", "diagnosis": None}
    assert report["confidence"] == {"location": 0.8, "injuries": None, "vitals": None,
                                     "note": "Detection confidence is not medical certainty."}
    assert {r["question"]: r["answer"] for r in report["responses"]}["breathing"] == "unknown"
    assert report["vitals"]["simulated"] is True
    assert "PRIVATE" not in json.dumps(report) and "invented" not in json.dumps(report)


@pytest.mark.parametrize("summary", [None, {"casualty": "c10", "answers": {"hurt": "no"}},
                                     {"casualty": "c1", "answers": "broken", "hurt_parts": None},
                                     {"casualty": "c1", "answers": {"hurt": []}}])
def test_missing_mismatched_or_malformed_dialogue_never_claims_no_injuries(summary):
    store = ParamedicReports(lambda: 1, dialogue_summary=lambda _: summary)
    store.observe([casualty(vitals={})])
    report = store.build(facts())[0]
    assert report["injuries"]["status"] == "unknown"
    assert report["vitals"]["breathing_rate"] is None
    assert all(r["answer"] == "unknown" for r in report["responses"])


def test_unavailable_dialogue_does_not_break_report_or_leak_exception():
    def unavailable(_):
        raise RuntimeError("PRIVATE error")
    store = ParamedicReports(lambda: 1, dialogue_summary=unavailable)
    store.observe([casualty()])
    report = store.build(facts())[0]
    assert report["dialogue_available"] is False
    assert "PRIVATE" not in json.dumps(report)


def test_no_reported_pain_does_not_become_a_diagnosis():
    store = ParamedicReports(lambda: 0, dialogue_summary=lambda cid: {"casualty": cid, "answers": {"hurt": "no"}})
    store.observe([casualty()])
    report = store.build(facts())[0]
    assert report["injuries"]["status"] == "none_reported"
    assert report["injuries"]["diagnosis"] is None


def test_last_observation_retained_and_sparse_updates_do_not_erase_other_casualty():
    now = [1]
    store = ParamedicReports(lambda: now[0], dialogue_summary=lambda _: None)
    first = casualty()
    store.observe([first, casualty("c10")])
    first["pos"][0] = 999
    now[0] = 5
    store.observe([casualty("c10", pos=[3, 4, 1], confidence=0.6)])
    one, ten = store.build(facts())
    assert one["location"]["pos"] == [1, 2, 0]
    assert one["location"]["observed_at"] == 1 and not one["location"]["currently_reported"]
    assert any("last observation" in text for text in one["unknowns"])
    assert ten["location"]["observed_at"] == 5 and ten["location"]["pos"] == [3, 4, 1]
    assert ten["confidence"]["location"] == 0.6


def test_snapshots_and_facts_do_not_alias_report_data():
    store = ParamedicReports(lambda: 1, dialogue_summary=lambda _: None)
    store.observe([casualty()])
    original = facts()
    before = copy.deepcopy(original)
    report = store.build(original)[0]
    report["actions"][0]["status"] = "changed"
    report["location"]["pos"][0] = 999
    assert original == before
    assert store.build(original)[0]["location"]["pos"][0] == 1


def test_guide_adapter_uses_existing_public_api_without_importing_voice(monkeypatch):
    monkeypatch.delitem(sys.modules, "voice", raising=False)
    assert guide_summary("c1") is None
    assert "voice" not in sys.modules
    monkeypatch.setitem(sys.modules, "voice", SimpleNamespace(GUIDE=SimpleNamespace(
        summary=lambda cid: {"casualty": cid, "answers": {"hear": "yes"}})))
    assert guide_summary("c1")["answers"] == {"hear": "yes"}


@pytest.mark.parametrize("text", ["report", " GENERATE REPORT ", "Paramedic report", "remote paramedic report"])
def test_report_commands_are_distinct_from_navigation(text):
    assert is_report_command(text)
    assert not is_report_command("send water to paramedic report room")


def test_real_bus_paramedic_command_preserves_gate_and_routing_and_writes_facts(tmp_path, caplog):
    async def scenario():
        import planner
        from coord.hub import Bus

        bus = Bus()
        router = await planner.start(bus)
        router.reporter.output_dir = tmp_path
        router.reporter.paramedics.dialogue_summary = lambda cid: {
            "casualty": cid, "answers": {"hear": "yes", "hurt": "yes", "bleeding": "unsure"},
            "hurt_parts": ["arm"]}
        try:
            await bus.publish("map/casualties", [casualty(), casualty("c10")])
            await bus.publish("route/proposed", {"id": "r1", "robot": "responder", "cells": [[0, 0, 0]],
                                                 "goal": "deliver water to c1", "model": "local-astar"})
            await bus.publish("gate/request", {"id": "g1", "kind": "risky_move", "route": "r1", "summary": "human review"})
            await bus.publish("gate/answer", {"id": "g1", "approved": False, "by": "operator"})
            router.loop.places = {"back room": [1, 2, 0]}

            def must_not_interpret(*_):
                raise AssertionError("paramedic report must not become a navigation command")

            router.loop.interpret = must_not_interpret
            await bus.publish("operator/command", {"text": "Paramedic report", "source": "typed"})
            message = next(m for m in reversed(bus.history) if m["topic"] == "report/handover")
            report = message["data"]["json"]
            one, ten = report["paramedic_reports"]
            assert one["id"] == "c1" and ten["id"] == "c10"
            assert one["approvals"][0]["status"] == "operator denied"
            assert ten["approvals"] == [] and ten["vitals"]["simulated"] is True
            assert not any(m["topic"] == "responder/action" for m in bus.history)
            assert router.loop.mission_args is None
            markdown = message["data"]["markdown"]
            assert "AFTERLIGHT" in markdown and "Remote paramedic reports" in markdown
            assert "operator denied" in markdown and "diagnosis unknown" in markdown
            assert next(tmp_path.glob("handover_*.md")).read_text(encoding="utf-8") == markdown
            assert not [r for r in caplog.records if r.levelname == "ERROR"]
        finally:
            router.task.cancel()
            await asyncio.gather(router.task, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize("move_route,expected", [(None, None), ("r1", "r1")])
def test_repeated_supply_commands_cannot_confirm_delivery_for_the_wrong_casualty(tmp_path, move_route, expected):
    from planner.report import ReportCollector
    from planner.tests.test_report import Bus

    reporter = ReportCollector(Bus(), output_dir=tmp_path)
    reporter.on_casualties([casualty(), casualty("c10")])
    for rid, cid in (("r1", "c1"), ("r10", "c10")):
        reporter.on_route({"id": rid, "robot": "responder", "cells": [[0, 0, 0]],
                           "goal": f"deliver water to {cid}", "model": "local-astar"})
        reporter.on_action({"action": "place_supply", "route": rid, "item": "water"})
    if move_route:
        reporter.on_log({"t": 2, "model": "sim", "physics": "mujoco", "outcome": "act",
                         "perception": f"responder at [0.0, 0.0], move {move_route}",
                         "reason": f"following route {move_route}"})
    reporter.on_log({"t": 3, "model": "sim", "physics": "mujoco", "outcome": "done",
                     "perception": "responder at [0.0, 0.0], place_supply water",
                     "reason": "placed water at [0.20, 0.00]"})
    report = reporter.snapshot()
    assert report["supplies_delivered"][0]["route"] == expected
    one, ten = report["paramedic_reports"]
    assert len(one["supplies_delivered"]) == (1 if expected == "r1" else 0)
    assert ten["supplies_delivered"] == []
    assert ten["actions"][0]["status"].startswith("commanded")
    assert ten["action_results"] == []
    if move_route:
        assert [r["outcome"] for r in one["action_results"]] == ["act", "done"]


def test_paramedic_markdown_escapes_casualty_identifiers_and_event_text(tmp_path):
    from planner.report import ReportCollector, render_markdown
    from planner.tests.test_report import Bus

    reporter = ReportCollector(Bus(), output_dir=tmp_path)
    reporter.on_casualties([casualty("<script>alert(1)</script>![x](bad)")])
    markdown = render_markdown(reporter.snapshot())
    assert "<script>" not in markdown and "![x]" not in markdown


def test_new_kit_supply_is_still_confirmed_only_by_matching_sim_placement(tmp_path):
    from planner.report import ReportCollector
    from planner.tests.test_report import Bus

    reporter = ReportCollector(Bus(), output_dir=tmp_path)
    reporter.on_casualties([casualty()])
    reporter.on_route({"id": "r1", "goal": "deliver bandage to c1", "cells": [[0, 0, 0]],
                       "robot": "responder", "model": "local-astar"})
    reporter.on_action({"action": "place_supply", "item": "bandage", "route": "r1"})
    assert reporter.snapshot()["paramedic_reports"][0]["supplies_delivered"] == []
    reporter.on_log({"model": "sim", "physics": "mujoco", "outcome": "done", "t": 2,
                     "perception": "responder at [0.0, 0.0], place_supply bandage",
                     "reason": "placed bandage at [0.20, 0.00]"})
    assert reporter.snapshot()["paramedic_reports"][0]["supplies_delivered"][0]["item"] == "bandage"


def test_development_fixture_replays_through_validated_bus_and_preserves_silence(tmp_path):
    async def scenario():
        from coord.hub import Bus
        from planner.report import ReportCollector

        fixture = json.loads((Path(__file__).parents[1] / "fixtures" / "paramedic.json").read_text(encoding="utf-8"))
        assert fixture["development_example"] is True
        bus = Bus()
        collector = ReportCollector(bus, output_dir=tmp_path,
                                    dialogue_summary=lambda cid: fixture["dialogue"].get(cid)).attach()
        for event in fixture["events"]:
            await bus.publish(event["topic"], event["data"])
        result = await collector.generate()
        one, ten = result["json"]["paramedic_reports"]
        assert len(one["supplies_delivered"]) == 1 and ten["supplies_delivered"] == []
        assert ten["responses"][0]["answer"] == "none"
        assert ten["injuries"]["status"] == "unknown"
        assert ten["approvals"][0]["answers"][0]["approved"] is False
        assert "Difficulty breathing: no" in result["markdown"]
        assert "Can hear the robot: no response recorded" in result["markdown"]
        assert bus.history[-1]["topic"] == "report/handover"
    asyncio.run(scenario())
