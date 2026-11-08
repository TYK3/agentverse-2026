"""Tests for perception/triage.py (Y3: Injury triage and first-aid gate)."""

import asyncio

from perception.triage import (
    ALLOWED_ITEMS,
    TRIAGE,
    Triager,
    extract_json_payload,
    gemini_triage,
    offline_triage_rules,
    triage_summary,
)


def sample_casualty(cid="c1", **extra):
    return {
        "id": cid,
        "pos": [2.0, 1.0, 0.1],
        "confidence": 0.85,
        "clues": ["thermal", "sound", "camera"],
        "vitals": {"breathing_rate": 14, "simulated": True},
        **extra,
    }


def test_offline_triage_respiratory_distress():
    cas = sample_casualty("c1")
    dialogue = {
        "casualty": "c1",
        "answers": {"breathing": "yes", "hurt": "yes", "move": "yes"},
        "hurt_parts": ["chest"],
    }
    assessment = offline_triage_rules(cas, dialogue)
    assert assessment.triage_level == "immediate"
    assert assessment.recommended_item == "first_aid_kit"
    assert assessment.needs_human is True
    assert "respiratory_distress" in assessment.injuries
    assert assessment.gate_request_id == "g_triage_c1"
    assert len(assessment.options) >= 2


def test_offline_triage_bleeding():
    cas = sample_casualty("c2", confidence=0.85)
    dialogue = {
        "casualty": "c2",
        "answers": {"bleeding": "yes", "hurt": "yes", "breathing": "no", "move": "yes", "walk": "yes"},
        "hurt_parts": [],
    }
    assessment = offline_triage_rules(cas, dialogue)
    assert assessment.triage_level == "urgent"
    assert assessment.recommended_item == "bandage"
    assert "external_hemorrhage" in assessment.injuries
    assert assessment.needs_human is False  # High confidence and clear single injury


def test_offline_triage_fracture_splint():
    cas = sample_casualty("c3", confidence=0.85)
    dialogue = {
        "casualty": "c3",
        "answers": {"walk": "no", "move": "no", "hurt": "yes", "bleeding": "no", "breathing": "no"},
        "hurt_parts": ["leg"],
    }
    assessment = offline_triage_rules(cas, dialogue)
    assert assessment.triage_level == "urgent"
    assert assessment.recommended_item == "splint"
    assert "limb_immobilization_or_fracture" in assessment.injuries


def test_offline_triage_hypothermia_blanket():
    cas = sample_casualty("c4", clues=["sound"], confidence=0.7)  # Acoustic only, no thermal peak
    dialogue = {
        "casualty": "c4",
        "answers": {"hear": "yes", "hurt": "no", "breathing": "no", "bleeding": "no"},
        "hurt_parts": [],
    }
    assessment = offline_triage_rules(cas, dialogue)
    assert assessment.recommended_item == "thermal_blanket"


def test_offline_triage_stable_water():
    cas = sample_casualty("c5", confidence=0.85)
    dialogue = {
        "casualty": "c5",
        "answers": {"hear": "yes", "hurt": "no", "breathing": "no", "bleeding": "no", "move": "yes", "walk": "yes"},
        "hurt_parts": [],
    }
    assessment = offline_triage_rules(cas, dialogue)
    assert assessment.triage_level == "delayed"
    assert assessment.recommended_item == "water"


def test_offline_triage_missing_dialogue_needs_human():
    cas = sample_casualty("c6", confidence=0.75)
    # No dialogue summary
    assessment = offline_triage_rules(cas, None)
    assert assessment.needs_human is True
    assert assessment.confidence <= 0.65
    assert assessment.gate_request_id == "g_triage_c6"
    assert any(opt["item"] in ALLOWED_ITEMS for opt in assessment.options)


def test_extract_json_payload():
    text1 = 'Here is the diagnosis: ```json\n{"triage_level": "urgent", "recommended_item": "splint"}\n```'
    assert extract_json_payload(text1) == {"triage_level": "urgent", "recommended_item": "splint"}

    text2 = '{"triage_level": "immediate", "recommended_item": "first_aid_kit"}'
    assert extract_json_payload(text2) == {"triage_level": "immediate", "recommended_item": "first_aid_kit"}

    assert extract_json_payload("not json") is None


def test_gemini_triage_fallback_off_mode(monkeypatch):
    monkeypatch.setenv("GEMINI_MODE", "off")
    cas = sample_casualty("c7")
    dialogue = {"casualty": "c7", "answers": {"bleeding": "yes"}}
    assessment = gemini_triage(cas, dialogue)
    assert assessment.source == "offline_rules"
    assert assessment.recommended_item == "bandage"


def test_gemini_triage_mock_model_response(monkeypatch):
    monkeypatch.setenv("GEMINI_MODE", "live")

    class FakeGem:
        def ask(self, *args, **kwargs):
            return (
                '```json\n'
                '{\n'
                '  "triage_level": "urgent",\n'
                '  "injuries": ["left_tibia_fracture"],\n'
                '  "hurt_parts": ["leg"],\n'
                '  "recommended_item": "splint",\n'
                '  "options": [{"item": "splint", "label": "Splint leg", "rationale": "Fracture"}],\n'
                '  "confidence": 0.88,\n'
                '  "needs_human": false,\n'
                '  "rationale": "Visible fracture requires splint immobilization"\n'
                '}\n'
                '```'
            )

    monkeypatch.setattr("perception.triage._gem", lambda: FakeGem())
    cas = sample_casualty("c8")
    assessment = gemini_triage(cas)
    assert assessment.source == "gemini-4-argon"
    assert assessment.triage_level == "urgent"
    assert assessment.recommended_item == "splint"
    assert assessment.confidence == 0.88
    assert assessment.needs_human is False


def test_triager_summary_for_paramedic_report():
    triager = Triager(dialogue_reader=lambda cid: {"casualty": cid, "answers": {"walk": "no"}})
    cas = sample_casualty("c9")
    triager.assess(cas)

    summary = triager.summary("c9")
    assert summary is not None
    assert summary["casualty"] == "c9"
    assert summary["recommended_item"] == "splint"
    assert isinstance(summary["confidence"], float)
    assert "triage_level" in summary


def test_global_triage_singleton():
    cas = sample_casualty("c11")
    TRIAGE.assess(cas, dialogue={"casualty": "c11", "answers": {"hurt": "no"}})
    assert triage_summary("c11") is not None
    assert triage_summary("c11")["recommended_item"] in ALLOWED_ITEMS


class FakeBus:
    def __init__(self):
        self.published = []
        self.subscriptions = {}

    def subscribe(self, topic, handler):
        self.subscriptions.setdefault(topic, []).append(handler)

    async def publish(self, topic, data):
        self.published.append((topic, data))


def test_triager_bus_events_human_review_and_approval():
    async def scenario():
        bus = FakeBus()
        # Mock dialogue where bleeding is unsure -> needs_human=True
        triager = Triager(dialogue_reader=lambda cid: {"casualty": cid, "answers": {"bleeding": "unsure"}})
        triager.attach(bus)

        cas = sample_casualty("c1")
        await triager.on_casualties([cas])

        # Expect gate/request and gate/decision (outcome=refer)
        topics = [t for t, _ in bus.published]
        assert "gate/request" in topics
        assert "gate/decision" in topics

        req_msg = next(d for t, d in bus.published if t == "gate/request")
        assert req_msg["id"] == "g_triage_c1"
        assert req_msg["kind"] == "risky_move"

        # Now simulate operator approval
        ans_action = await triager.on_answer({"id": "g_triage_c1", "approved": True, "by": "operator"})
        assert ans_action is None  # a supply choice is not a delivery route
        assert "g_triage_c1" not in triager.pending_gates
        recommendation = next(d for t, d in bus.published if t == "casualty/triage")
        assert recommendation["recommended_action"] in ALLOWED_ITEMS
        assert not any(t == "responder/action" for t, _ in bus.published)

    asyncio.run(scenario())


def test_triager_bus_events_denial():
    async def scenario():
        bus = FakeBus()
        triager = Triager(dialogue_reader=lambda cid: {"casualty": cid, "answers": {"bleeding": "unsure"}})
        triager.attach(bus)

        cas = sample_casualty("c1")
        await triager.on_casualties([cas])

        # Operator denies request
        ans_action = await triager.on_answer({"id": "g_triage_c1", "approved": False, "by": "operator"})
        assert ans_action is None
        # responder/action must not be published
        assert not any(t == "responder/action" for t, _ in bus.published)

    asyncio.run(scenario())


def test_triager_autonomous_action_on_high_confidence():
    async def scenario():
        bus = FakeBus()
        # High confidence single injury (bleeding: yes, hurt: yes, confidence 0.85) -> needs_human=False
        triager = Triager(dialogue_reader=lambda cid: {
            "casualty": cid,
            "answers": {"bleeding": "yes", "hurt": "yes", "breathing": "no", "move": "yes", "walk": "yes"},
        })
        triager.attach(bus)

        cas = sample_casualty("c2", confidence=0.85)
        await triager.on_casualties([cas])

        # Clinical confidence selects the item; the planner still routes delivery.
        dec = next(d for t, d in bus.published if t == "gate/decision")
        assert dec["outcome"] == "act"
        recommendation = next(d for t, d in bus.published if t == "casualty/triage")
        assert recommendation["recommended_action"] == "bandage"
        assert not any(t == "responder/action" for t, _ in bus.published)

    asyncio.run(scenario())
