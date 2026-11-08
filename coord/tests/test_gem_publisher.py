"""G1 completed receipts reach the validating hub once, without making model calls."""

import asyncio
from collections import deque
from types import SimpleNamespace

import pytest

from coord import gem, hub


def test_receipts_validate_and_are_forwarded_once_per_invocation(monkeypatch):
    monkeypatch.setattr(gem, "MODE", "off")
    monkeypatch.setattr(gem, "_receipts", deque(maxlen=200))
    monkeypatch.setattr(gem, "_c", lambda: pytest.fail("publisher called SDK"))
    target = hub.Bus()
    with pytest.raises(gem.GeminiOff):
        gem.ask("embodied_reasoning", "frame", route="r1", evidence_ids=["scan-7"])
    ticks = []

    async def advance(_):
        ticks.append(1)
        if len(ticks) == 1:
            with pytest.raises(gem.GeminiOff):
                gem.ask("fast_subagent", "frame", route="r1")
        if len(ticks) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(hub.asyncio, "sleep", advance)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(hub.publish_gemini_status(target, gem))
    forwarded = [entry["data"] for entry in target.history if entry["topic"] == "gemini/receipt"]
    assert len(forwarded) == 2 and len({entry["id"] for entry in forwarded}) == 2
    assert all(entry["route"] == "r1" and entry["source"] == "disabled" for entry in forwarded)
    assert len([entry for entry in target.history if entry["topic"] == "status/gemini"]) == 3


def test_status_publisher_still_supports_legacy_status_only_provider(monkeypatch):
    target = hub.Bus()
    old_gem = SimpleNamespace(status=lambda: {"mode": "off", "calls_last_hour": 0, "stand_ins": []})

    async def stop(_):
        raise asyncio.CancelledError

    monkeypatch.setattr(hub.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(hub.publish_gemini_status(target, old_gem))
    assert [entry["topic"] for entry in target.history] == ["status/gemini"]
