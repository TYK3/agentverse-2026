"""Tests for emergency call preparation (T22).

Validates:
1. Emergency report text formats location cell, clues, and vitals.
2. Estimated vitals are strictly marked as simulated.
3. Prepared payload conforms to CONTRACT.md 'gate/request' shape with kind='emergency_call'.
4. Bus publishing sends 'gate/request' without directly placing calls.
"""

import asyncio

from voice import emergency


def test_prepare_emergency_text():
    casualty = {
        "id": "c1",
        "pos": [2.0, 1.0, 0.1],
        "confidence": 0.85,
        "clues": ["pose", "thermal", "sound"],
        "vitals": {"breathing_rate": 14, "simulated": True},
    }
    text = emergency.prepare_emergency_text(casualty, cell=[3, 4, 0])
    assert "c1" in text
    assert "cell [3, 4, 0]" in text
    assert "pose, thermal, sound" in text
    assert "breathing_rate=14 (SIMULATED)" in text
    assert "Human approval required" in text


def _check_gate_request(payload):
    try:
        from coord.messages import TOPICS
        TOPICS["gate/request"].model_validate(payload)
    except (ImportError, KeyError):
        assert set(payload.keys()) >= {"id", "kind", "summary", "route"}
        assert payload["kind"] in ("risky_move", "enter_at_risk", "emergency_call")
        assert isinstance(payload["id"], str)
        assert isinstance(payload["summary"], str)
        assert isinstance(payload["route"], str)


def test_prepare_gate_request_contract_shape():
    casualty = {
        "id": "c1",
        "pos": [2.0, 1.0, 0.1],
        "confidence": 0.9,
        "clues": ["pose", "sound"],
        "vitals": {"breathing_rate": 12, "simulated": True},
    }
    gate_req = emergency.prepare_gate_request(casualty, cell=[3, 4, 0])
    assert gate_req["id"] == "g_emerg_c1"
    assert gate_req["kind"] == "emergency_call"
    assert "c1" in gate_req["summary"]
    assert "(SIMULATED)" in gate_req["summary"]
    assert "route" in gate_req
    _check_gate_request(gate_req)


def test_publish_emergency_request():
    class FakeBus:
        def __init__(self):
            self.published = []

        async def publish(self, topic, data):
            self.published.append((topic, data))

    bus = FakeBus()
    casualty = {
        "id": "c2",
        "pos": [1.5, -2.0, 0.0],
        "confidence": 0.75,
        "clues": ["thermal"],
        "vitals": {"heart_rate": 90, "simulated": True},
    }

    req = asyncio.run(emergency.publish_emergency_request(bus, casualty))
    assert req["id"] == "g_emerg_c2"
    assert len(bus.published) == 1
    topic, data = bus.published[0]
    assert topic == "gate/request"
    assert data["kind"] == "emergency_call"
    assert "c2" in data["summary"]
    assert "(SIMULATED)" in data["summary"]
