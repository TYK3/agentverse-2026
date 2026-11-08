"""G1f: a bad receipt must not stop status updates or later valid receipts."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from coord import hub


def receipt(call_id="gem-valid"):
    data = json.loads((Path(__file__).parents[1] / "fixtures/gemini__receipt.json").read_text())["data"]
    return {**data, "id": call_id}


def provider(getter):
    return SimpleNamespace(status=lambda: {"mode": "off", "calls_last_hour": 0, "stand_ins": []}, receipts=getter)


def run_polls(monkeypatch, target, gem, polls=3):
    ticks = []

    async def advance(_):
        ticks.append(1)
        if len(ticks) == polls:
            raise asyncio.CancelledError

    monkeypatch.setattr(hub.asyncio, "sleep", advance)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(hub.publish_gemini_status(target, gem))


def messages(target, topic):
    return [item["data"] for item in target.history if item["topic"] == topic]


def test_receipt_getter_failure_recovers_without_duplicating_prior_records(monkeypatch, caplog):
    target, calls = hub.Bus(), []

    def getter():
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("PRIVATE-INPUT")
        return [receipt()] if len(calls) == 1 else [receipt(), receipt("gem-next")]

    run_polls(monkeypatch, target, provider(getter))
    assert len(messages(target, "status/gemini")) == 3
    assert [item["id"] for item in messages(target, "gemini/receipt")] == ["gem-valid", "gem-next"]
    assert "PRIVATE-INPUT" not in caplog.text


def test_malformed_records_do_not_block_later_valid_receipts_or_status(monkeypatch, caplog):
    target = hub.Bus()
    bad = {**receipt("gem-bad"), "prompt": "PRIVATE-INPUT"}
    gem = provider(lambda: [None, {"id": []}, bad, receipt(), receipt()])
    run_polls(monkeypatch, target, gem)
    assert len(messages(target, "status/gemini")) == 3
    assert [item["id"] for item in messages(target, "gemini/receipt")] == ["gem-valid"]
    assert "PRIVATE-INPUT" not in caplog.text


def test_failed_receipt_delivery_retries_while_status_keeps_running(monkeypatch, caplog):
    class FlakyBus(hub.Bus):
        attempts = 0

        async def publish(self, topic, data):
            if topic == "gemini/receipt":
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("PRIVATE-INPUT")
            await super().publish(topic, data)

    target = FlakyBus()
    run_polls(monkeypatch, target, provider(lambda: [receipt()]))
    assert len(messages(target, "status/gemini")) == 3 and target.attempts == 2
    assert len(messages(target, "gemini/receipt")) == 1
    assert "PRIVATE-INPUT" not in caplog.text


def test_receipt_guard_never_swallows_publisher_cancellation(monkeypatch):
    class CancelledBus(hub.Bus):
        async def publish(self, topic, data):
            if topic == "gemini/receipt":
                raise asyncio.CancelledError
            await super().publish(topic, data)

    target = CancelledBus()
    run_polls(monkeypatch, target, provider(lambda: [receipt()]))
    assert len(messages(target, "status/gemini")) == 1
