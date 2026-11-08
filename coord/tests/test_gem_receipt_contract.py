"""G1 wire validation prevents replay/disabled receipts from claiming live usage."""

import json
from pathlib import Path

import pytest

from coord.messages import validate_payload


def fixture():
    path = Path(__file__).parents[1] / "fixtures/gemini__receipt.json"
    return json.loads(path.read_text())["data"]


@pytest.mark.parametrize("changes", [
    {"usage": {"total_tokens": 1}}, {"provider_id": "invented"},
    {"live_attempts": 1}, {"prompt": "raw text forbidden"}, {"outcome": "ok"},
])
def test_disabled_receipt_cannot_claim_live_activity_or_raw_input(changes):
    with pytest.raises(ValueError):
        validate_payload("gemini/receipt", {**fixture(), **changes})


def test_replay_attributes_old_usage_under_origin_only():
    payload = {**fixture(), "mode": "replay", "source": "cache", "outcome": "ok",
               "source_call_id": "gem-original", "cache_origin": {"id": "gem-original",
               "provider_id": "provider-old", "model_requested": "requested", "model_reported": None,
               "usage": {"total_tokens": 7}}}
    assert validate_payload("gemini/receipt", payload) == payload
    with pytest.raises(ValueError):
        validate_payload("gemini/receipt", {**payload, "usage": {"total_tokens": 7}})
