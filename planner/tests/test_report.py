"""Fixture handover completeness, privacy, provenance and persistence."""

import asyncio
import json
import time
from pathlib import Path

import pytest

from planner.report import ReportCollector

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "handover.json"


class Bus:
    def __init__(self):
        self.subs, self.messages = {}, []

    def subscribe(self, topic, callback):
        self.subs.setdefault(topic, []).append(callback)

    async def publish(self, topic, data):
        self.messages.append({"topic": topic, "data": data})
        for callback in self.subs.get(topic, []):
            result = callback(data)
            if asyncio.iscoroutine(result):
                await result


def test_fixture_report_preserves_replans_approvals_and_labels(tmp_path):
    async def scenario():
        bus, now = Bus(), [0]
        collector = ReportCollector(bus, output_dir=tmp_path, clock=lambda: now[0]).attach()
        for envelope in json.loads(FIXTURE.read_text(encoding="utf-8")):
            now[0] += 1
            await bus.publish(envelope["topic"], envelope["data"])
        result = await collector.generate()
        report, text = result["json"], result["markdown"]
        assert "aftershock moved b7" in text and "old route dropped" in text
        assert "simulated" in text and "estimate" in text
        assert [a["id"] for a in report["approvals"]] == ["g1", "g2"]
        assert [a["answers"][0]["approved"] for a in report["approvals"]] == [True, False]
        assert all(a["answers"][0]["by"] == "operator" and a["requested_at"] > 0 for a in report["approvals"])
        assert report["hazards"]["before"][0]["status"] == "at_risk"
        assert report["hazards"]["after"][0]["status"] == "collapsed"
        assert report["supplies_delivered"] == [
            {"item": "water", "pos": [0.2, 0.0], "t": 20, "simulated": True, "route": "r1"}]
        assert "Simulated delivery confirmed" in text
        assert result["path"].read_text(encoding="utf-8") == text
        assert result["path"].name.startswith("handover_")
        assert bus.messages[-1]["topic"] == "report/handover"
        assert set(bus.messages[-1]["data"]) == {"json", "markdown"}
        from coord.messages import validate_payload
        validate_payload("report/handover", bus.messages[-1]["data"])
    asyncio.run(scenario())


class Gem:
    MODE = "live"

    def __init__(self, *, failure=None, changed_facts=False, delay=0, reply=None):
        self.calls, self.stand_ins = [], set()
        self.failure, self.changed_facts, self.delay = failure, changed_facts, delay
        self.reply = reply

    def ask(self, model_key, prompt, **kwargs):
        self.calls.append((model_key, kwargs))
        time.sleep(self.delay)
        if self.failure:
            raise self.failure
        if self.reply is not None:
            return self.reply
        report = json.loads(prompt.split("\n", 1)[1])
        draft = {key: report[key] for key in ("summary", "casualties", "hazards", "actions", "approvals", "open_risks")}
        draft["summary"] = "Rescue handover draft; see recorded observations and outstanding risks."
        if self.changed_facts:
            draft["actions"] = [{"action": "invented delivery"}]
        return json.dumps(draft)

    def mark_stand_in(self, feature):
        self.stand_ins.add(feature)


def test_off_mode_renders_template_without_spending_a_call(tmp_path):
    async def scenario():
        gem = Gem()
        gem.MODE = "off"
        reporter = ReportCollector(Bus(), output_dir=tmp_path, gem=gem)
        result = await reporter.generate()
        assert gem.calls == [] and gem.stand_ins == {"handover_report"}
        assert "GEMINI_MODE=off" in result["json"]["source"]
    asyncio.run(scenario())


def test_model_draft_is_structured_and_called_once_for_concurrent_requests(tmp_path):
    async def scenario():
        gem = Gem()
        reporter = ReportCollector(Bus(), output_dir=tmp_path, gem=gem)
        first, second = await asyncio.gather(reporter.generate(), reporter.generate())
        assert len(gem.calls) == 1
        assert gem.calls[0][0] == "fast_subagent"
        assert gem.calls[0][1]["feature"] == "handover_report"
        assert "gemini-3.8-flash draft" in first["json"]["source"]
        assert first["json"] == second["json"]
        assert first["path"] != second["path"]
    asyncio.run(scenario())


@pytest.mark.parametrize("gem", [Gem(failure=RuntimeError("PRIVATE_ERROR_DETAIL")), Gem(changed_facts=True)])
def test_model_failure_or_changed_facts_falls_back_without_retry(tmp_path, gem):
    async def scenario():
        reporter = ReportCollector(Bus(), output_dir=tmp_path, gem=gem)
        for _ in range(2):
            result = await reporter.generate()
            assert "plain template" in result["json"]["source"]
            assert "PRIVATE_ERROR_DETAIL" not in result["markdown"]
            assert result["json"]["actions"] == []
        assert len(gem.calls) == 1 and gem.stand_ins == {"handover_report"}
    asyncio.run(scenario())


def test_model_timeout_uses_template(tmp_path):
    async def scenario():
        gem = Gem(delay=0.05)
        reporter = ReportCollector(Bus(), output_dir=tmp_path, gem=gem, model_timeout=0.001)
        result = await reporter.generate()
        assert "TimeoutError" in result["json"]["source"]
        assert len(gem.calls) == 1
    asyncio.run(scenario())


def test_updated_events_do_not_reuse_an_old_model_summary(tmp_path):
    async def scenario():
        gem = Gem()
        reporter = ReportCollector(Bus(), output_dir=tmp_path, gem=gem)
        await reporter.generate()
        reporter.on_world_change({"kind": "aftershock", "t": 30, "moved_blocks": ["b7"]})
        result = await reporter.generate()
        assert "predates current events" in result["json"]["source"]
        assert "aftershock" in result["markdown"]
        assert len(gem.calls) == 1
    asyncio.run(scenario())


def test_facts_arriving_during_model_call_appear_in_the_report(tmp_path):
    async def scenario():
        reporter = ReportCollector(Bus(), output_dir=tmp_path, gem=Gem(delay=0.05))
        task = asyncio.create_task(reporter.generate())
        await asyncio.sleep(0.01)
        reporter.on_world_change({"kind": "aftershock", "t": 30, "moved_blocks": ["b7"]})
        result = await task
        assert "aftershock" in result["markdown"] and "predates current events" in result["json"]["source"]
    asyncio.run(scenario())


def test_timeout_status_and_unmatched_answers_are_preserved(tmp_path):
    async def scenario():
        reporter = ReportCollector(Bus(), output_dir=tmp_path)
        reporter.on_request({"id": "g1", "kind": "risky_move", "summary": "obstacle", "route": "r1"})
        reporter.on_log({"outcome": "hold", "perception": "gate g1", "reason": "approval timeout: refused",
                         "model": "local-astar", "physics": ""})
        reporter.on_answer({"id": "g1", "approved": True, "by": "operator"})
        reporter.on_answer({"id": "g999", "approved": True, "by": "operator"})
        result = await reporter.generate()
        assert result["json"]["approvals"][0]["status"] == "approval timeout: refused"
        assert len(result["json"]["unmatched_answers"]) == 1
        assert "grant no permission" in result["markdown"]
    asyncio.run(scenario())


@pytest.mark.parametrize("model,outcome,reason", [
    ("local-astar", "done", "placed water at [0.20, 0.00]"),
    ("sim", "queued", "placed water at [0.20, 0.00]"),
    ("sim", "refused", "not carrying water"),
    ("sim", "done", "gripper open, not holding water"),
])
def test_commands_and_other_logs_cannot_claim_a_delivery(tmp_path, model, outcome, reason):
    reporter = ReportCollector(Bus(), output_dir=tmp_path)
    reporter.on_action({"action": "place_supply", "route": "r1", "item": "water"})
    reporter.on_log({"model": model, "physics": "mujoco", "outcome": outcome, "reason": reason,
                     "perception": "responder at [0.1, 0.0], place_supply water", "t": 1})
    assert reporter.snapshot()["supplies_delivered"] == []


def test_hub_entry_point_attaches_reporter_without_reinterpreting_report_as_a_goal(tmp_path):
    async def scenario():
        import planner

        bus = Bus()
        router = await planner.start(bus)
        router.reporter.output_dir = tmp_path
        router.loop.places = {"back room": [8, 3, 0]}

        def must_not_interpret(*_):
            raise AssertionError("a report command must not reach the navigation interpreter")

        router.loop.interpret = must_not_interpret
        try:
            await bus.publish("operator/command", {"text": "report", "source": "typed"})
            assert bus.messages[-1]["topic"] == "report/handover"
            assert router.loop.mission_args is None
            assert len(list(tmp_path.glob("handover_*.md"))) == 1
        finally:
            router.task.cancel()
            await asyncio.gather(router.task, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize("reply", ["not JSON", "{}"])
def test_malformed_model_reply_falls_back_to_the_template(tmp_path, reply):
    async def scenario():
        reporter = ReportCollector(Bus(), output_dir=tmp_path, gem=Gem(reply=reply))
        result = await reporter.generate()
        assert "plain template" in result["json"]["source"]
        assert result["json"]["supplies_delivered"] == []
    asyncio.run(scenario())


def test_reentrant_answers_and_replayed_requests_keep_the_answer_history(tmp_path):
    async def scenario():
        bus = Bus()

        async def answer_immediately(request):
            await bus.publish("gate/answer", {"id": request["id"], "approved": True, "by": "operator"})

        bus.subscribe("gate/request", answer_immediately)
        reporter = ReportCollector(bus, output_dir=tmp_path).attach()
        request = {"id": "g1", "kind": "risky_move", "summary": "obstacle", "route": "r1"}
        await bus.publish("gate/request", request)
        reporter.on_request(request)
        result = await reporter.generate()
        assert result["json"]["approvals"][0]["answers"][0]["approved"] is True
        assert result["json"]["unmatched_answers"] == []
    asyncio.run(scenario())


def test_collector_ignores_sensor_images_and_unapproved_extra_fields(tmp_path):
    async def scenario():
        bus = Bus()
        collector = ReportCollector(bus, output_dir=tmp_path).attach()
        await bus.publish("sensors/scout", {"camera": "PRIVATE_IMAGE_BYTES"})
        await bus.publish("map/casualties", [{"id": "c1", "pos": [1, 2, 0], "confidence": 0.7,
            "clues": ["thermal"], "face": "PRIVATE_FACE_BYTES", "image": "PRIVATE_IMAGE_BYTES",
            "vitals": {"breathing_rate": 14, "simulated": True, "crop": "PRIVATE_IMAGE_BYTES"}}])
        report = await collector.generate()
        assert "PRIVATE_" not in json.dumps(report["json"]) + report["markdown"]
        assert "camera" not in json.dumps(report["json"])
        assert report["json"]["casualties"][0]["vitals"]["simulated"] is True
    asyncio.run(scenario())


def test_map_deltas_accumulate_and_resolution_change_clears_counts(tmp_path):
    collector = ReportCollector(Bus(), output_dir=tmp_path)
    collector.on_map({"res": 0.1, "cells": [{"cell": [0, 0, 0], "state": "seen", "occupied": False}]})
    collector.on_map({"res": 0.1, "cells": [{"cell": [1, 0, 0], "state": "inferred", "occupied": True}]})
    assert collector.snapshot()["map"] == {"seen": 1, "inferred": 1, "unknown": 0, "occupied": 1, "res": 0.1}
    collector.on_map({"res": 0.05, "cells": []})
    assert collector.snapshot()["map"]["seen"] == 0


def test_report_command_writes_and_publishes_only_for_report_requests(tmp_path):
    async def scenario():
        bus = Bus()
        ReportCollector(bus, output_dir=tmp_path).attach()
        await bus.publish("operator/command", {"text": "send water", "source": "typed"})
        assert not list(tmp_path.iterdir())
        await bus.publish("operator/command", {"text": "report", "source": "typed"})
        assert len(list(tmp_path.glob("handover_*.md"))) == 1
        assert bus.messages[-1]["topic"] == "report/handover"
    asyncio.run(scenario())
