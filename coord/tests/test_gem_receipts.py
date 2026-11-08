"""G1: fake SDK responses only, without credentials or network even in live-mode tests."""

import json
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from coord import gem


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for key, value in {"CACHE": tmp_path / "cache", "MODE": "off", "CAP": 300,
                       "_calls": [], "_receipts": deque(maxlen=200)}.items():
        monkeypatch.setattr(gem, key, value)
    monkeypatch.setattr(gem, "_c", lambda: pytest.fail("unexpected SDK access"))
    monkeypatch.setattr(gem.time, "sleep", lambda _: None)


def sdk(monkeypatch, replies):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        value = replies.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(gem, "_c", lambda: SimpleNamespace(interactions=SimpleNamespace(create=create)))
    return calls


def response(text="inspection", **extra):
    return SimpleNamespace(output_text=text, id="provider-123", model="reported-model", **extra)


def test_off_has_a_linked_receipt_but_no_sdk_or_raw_input():
    with pytest.raises(gem.GeminiOff) as error:
        gem.ask("embodied_reasoning", "private-camera-frame", route="r1", evidence_ids=["scan-7"])
    receipt = error.value.gemini_receipt
    assert (receipt["source"], receipt["outcome"], receipt["live_attempts"]) == ("disabled", "off", 0)
    assert receipt["attempts"] == [] and receipt["route"] == "r1" and receipt["evidence_ids"] == ["scan-7"]
    assert "private-camera-frame" not in json.dumps(gem.receipts()) and not gem.CACHE.exists()


def test_live_usage_is_observed_and_linkage_never_reaches_sdk(monkeypatch):
    monkeypatch.setattr(gem, "MODE", "live")
    calls = sdk(monkeypatch, [response(usage=SimpleNamespace(total_input_tokens=7, total_output_tokens=3, total_tokens=12))])
    result = gem.ask_with_receipt("fast_subagent", "frame", route="r1", evidence_ids=["scan-7"])
    assert result.text == "inspection" and result.receipt["provider_id"] == "provider-123"
    assert result.receipt["model_reported"] == "reported-model"
    assert result.receipt["usage"] == {"total_input_tokens": 7, "total_output_tokens": 3, "total_tokens": 12}
    assert result.receipt["elapsed_ms"] >= 0 and result.receipt["live_attempts"] == 1
    assert "route" not in calls[0] and "evidence_ids" not in calls[0]


def test_replay_keeps_exact_text_with_a_new_id_and_original_usage_only(monkeypatch):
    monkeypatch.setattr(gem, "MODE", "live")
    calls = sdk(monkeypatch, [response("first\r\nsecond\n", usage={"total_tokens": 5})])
    first = gem.ask_with_receipt("fast_subagent", "frame", route="r1")
    monkeypatch.setattr(gem, "MODE", "replay")
    cached = gem.ask_with_receipt("fast_subagent", "frame", route="r2")
    assert cached.text == first.text and len(calls) == 1
    receipt = cached.receipt
    assert receipt["id"] != first.receipt["id"] and receipt["source_call_id"] == first.receipt["id"]
    assert receipt["source"] == "cache" and receipt["route"] == "r2"
    assert receipt["usage"] is None and receipt["provider_id"] is None
    assert receipt["cache_origin"]["usage"] == {"total_tokens": 5}
    assert receipt["live_attempts"] == 0 and gem.status()["calls_last_hour"] == 1


@pytest.mark.parametrize("metadata", [None, "not-json", {"source": "live", "id": "false", "output_sha256": "mismatch"}])
def test_legacy_or_mismatched_cache_never_invents_provider_provenance(monkeypatch, metadata):
    monkeypatch.setattr(gem, "MODE", "replay")
    path = gem._cache_file("fast_subagent", "frame", "medium", {})
    path.parent.mkdir()
    path.write_text("legacy answer", encoding="utf-8")
    if metadata is not None:
        path.with_suffix(".receipt.json").write_text(
            json.dumps(metadata) if isinstance(metadata, dict) else metadata, encoding="utf-8")
    receipt = gem.ask_with_receipt("fast_subagent", "frame").receipt
    assert receipt["source"] == "cache" and receipt["source_call_id"] is None
    assert receipt["provider_id"] is None and receipt["usage"] is None


def test_retry_cap_stops_before_the_next_sdk_attempt(monkeypatch):
    monkeypatch.setattr(gem, "MODE", "live")
    monkeypatch.setattr(gem, "CAP", 2)
    calls = sdk(monkeypatch, [RuntimeError("503"), RuntimeError("429"), response()])
    with pytest.raises(gem.GeminiCap) as error:
        gem.ask("fast_subagent", "frame")
    receipt = error.value.gemini_receipt
    assert len(calls) == receipt["live_attempts"] == len(receipt["attempts"]) == 2
    assert receipt["outcome"] == "cap_reached" and gem.status()["calls_last_hour"] == 2


def test_permanent_failure_keeps_exception_but_omits_its_sensitive_text(monkeypatch):
    monkeypatch.setattr(gem, "MODE", "live")
    failure = RuntimeError("400 private-input-and-key")
    calls = sdk(monkeypatch, [failure, response()])
    with pytest.raises(RuntimeError) as error:
        gem.ask("fast_subagent", "private-input-and-key")
    assert error.value is failure and len(calls) == 1
    receipt = gem.receipts()[0]
    assert receipt["outcome"] == "error" and receipt["error_type"] == "RuntimeError"
    assert "private-input-and-key" not in json.dumps(receipt)


def test_missing_usage_is_unknown_not_zero(monkeypatch):
    monkeypatch.setattr(gem, "MODE", "live")
    sdk(monkeypatch, [response()])
    assert gem.ask_with_receipt("fast_subagent", "frame").receipt["usage"] is None


def test_cache_failure_does_not_retry_or_discard_provider_success(monkeypatch):
    monkeypatch.setattr(gem, "MODE", "live")
    calls = sdk(monkeypatch, [response()])

    def broken_cache(*args):
        raise PermissionError("private-path")

    monkeypatch.setattr(gem, "_atomic_write", broken_cache)
    result = gem.ask_with_receipt("fast_subagent", "frame")
    assert result.text == "inspection" and len(calls) == 1
    assert result.receipt["outcome"] == "ok" and result.receipt["cache_write_error"] == "PermissionError"


def test_er_uses_same_door_and_keeps_text_return_type(monkeypatch):
    monkeypatch.setattr(gem, "MODE", "live")
    calls = sdk(monkeypatch, [response()])
    assert gem.er("frame", route="r2", evidence_ids=["camera-8"]) == "inspection"
    assert calls[0]["model"] == "gemini-robotics-er-2-preview" and gem.receipts()[0]["route"] == "r2"


def test_history_is_bounded_and_returned_copies_cannot_rewrite_it():
    for _ in range(205):
        with pytest.raises(gem.GeminiOff):
            gem.ask("fast_subagent", "frame")
    snapshot = gem.receipts()
    assert len(snapshot) == 200
    snapshot[-1]["outcome"] = "fake-success"
    assert gem.receipts()[-1]["outcome"] == "off"


def test_concurrent_disabled_calls_have_unique_ids_without_sdk_activity():
    def disabled(_):
        try:
            gem.ask("fast_subagent", "frame")
        except gem.GeminiOff as error:
            return error.gemini_receipt["id"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(disabled, range(32)))
    assert len(set(ids)) == len(gem.receipts()) == 32 and gem.status()["calls_last_hour"] == 0
