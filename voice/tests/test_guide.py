"""Tests for the guide voice (Y5): reassure, ask injury questions, guide walkers out."""

import asyncio

import pytest

import voice
from voice import guide, speak

RES = 0.05
# Responder route from the entrance (0,0) to a casualty at about (0.525, 0.525):
# 10 cells east, then 10 cells north.
ROUTE = [[i, 0, 0] for i in range(11)] + [[10, j, 0] for j in range(1, 11)]
CASUALTY = {"id": "c1", "pos": [0.525, 0.525, 0.0], "confidence": 0.8, "clues": ["sound"],
            "vitals": {"breathing_rate": 14, "simulated": True}}


def texts(lines):
    return [line["text"] for line in lines]


def answer_all(g, now, answers):
    out = []
    for text in answers:
        out = g.hear("c1", text, now)
    return out


def ready_guide():
    g = guide.Guide()
    g.on_cells({"t": 0, "res": RES, "cells": []})
    g.on_route_proposed({"id": "r1", "robot": "responder", "cells": ROUTE, "goal": "water to c1",
                         "model": "local-astar"})
    return g


WALKER = ["yes", "my arm hurts a bit", "no", "no", "yes", "yes I can walk"]


def test_new_casualty_is_reassured_then_asked():
    g = guide.Guide()
    lines = g.on_casualties([CASUALTY], now=0)
    assert texts(lines) == [guide.GREETING, guide.QUESTIONS[0][1]]
    assert all(line["to"] == "casualty" and line["lang"] == "auto" for line in lines)
    assert g.on_casualties([CASUALTY], now=1) == []  # greeted once only


def test_questions_are_asked_in_order_and_recorded():
    g = guide.Guide()
    g.on_casualties([CASUALTY], now=0)
    asked = [texts(g.hear("c1", a, now=1))[0] for a in WALKER[:-1]]
    assert asked == [q for _, q in guide.QUESTIONS[1:]]
    s = g.summary("c1")
    assert s["answers"] == {"hear": "yes", "hurt": "yes", "breathing": "no", "bleeding": "no",
                            "move": "yes"}
    assert s["hurt_parts"] == ["arm"]
    assert "not a diagnosis" in s["note"]


def test_walker_is_guided_out_along_the_reversed_verified_route():
    g = ready_guide()
    g.on_route_verified({"id": "r1", "ok": True, "unstable_cells": [], "detail": ""}, now=0)
    g.on_casualties([CASUALTY], now=0)
    lines = answer_all(g, 1, WALKER)
    assert all(line["intent"] == "guide_exit" for line in lines)
    assert texts(lines) == [
        "I found a safe way out. Stand up slowly. Follow these steps.",
        "Walk slowly towards the robot's light, a step or two.",
        "Turn right, then walk a step or two.",
        guide.ARRIVED,
    ]
    assert g.summary("c1")["can_walk"] is True


def test_walker_waits_until_a_route_is_verified():
    g = ready_guide()
    g.on_casualties([CASUALTY], now=0)
    assert texts(answer_all(g, 1, WALKER)) == [guide.FINDING_WAY]
    lines = g.on_route_verified({"id": "r1", "ok": True, "unstable_cells": [], "detail": ""}, now=2)
    assert lines[0]["intent"] == "guide_exit" and lines[-1]["text"] == guide.ARRIVED


def test_rejected_route_is_never_used():
    g = ready_guide()
    g.on_route_verified({"id": "r1", "ok": False, "unstable_cells": [[3, 0, 0]], "detail": "b7"},
                        now=0)
    g.on_casualties([CASUALTY], now=0)
    assert texts(answer_all(g, 1, WALKER)) == [guide.FINDING_WAY]


def test_route_ending_elsewhere_is_not_their_exit():
    g = ready_guide()
    g.on_route_verified({"id": "r1", "ok": True, "unstable_cells": [], "detail": ""}, now=0)
    far = dict(CASUALTY, pos=[5.0, 5.0, 0.0])
    g.on_casualties([far], now=0)
    assert texts(answer_all(g, 1, WALKER)) == [guide.FINDING_WAY]


@pytest.mark.parametrize("answers", [
    ["yes", "my neck hurts", "no", "no", "yes", "yes"],   # possible spinal injury
    ["yes", "no", "yes it is hard", "no", "yes", "yes"],  # trouble breathing
    ["yes", "my leg", "no", "no", "no", "yes"],           # cannot move limbs
    ["yes", "no", "no", "no", "yes", "no I can't"],       # says they cannot walk
])
def test_non_walkers_are_told_to_stay_still(answers):
    g = ready_guide()
    g.on_route_verified({"id": "r1", "ok": True, "unstable_cells": [], "detail": ""}, now=0)
    g.on_casualties([CASUALTY], now=0)
    assert texts(answer_all(g, 1, answers)) == [guide.STAY_STILL]
    assert g.summary("c1")["can_walk"] is False


def test_aftershock_stops_a_walker_and_drops_the_route():
    g = ready_guide()
    g.on_route_verified({"id": "r1", "ok": True, "unstable_cells": [], "detail": ""}, now=0)
    g.on_casualties([CASUALTY], now=0)
    answer_all(g, 1, WALKER)
    lines = g.on_world_change({"kind": "aftershock", "t": 3, "moved_blocks": ["b7"]}, now=3)
    assert texts(lines) == [guide.AFTERSHOCK]
    assert g.verified == {}
    # Re-verified after the re-plan: guided again from the start.
    lines = g.on_route_verified({"id": "r1", "ok": True, "unstable_cells": [], "detail": ""}, now=9)
    assert lines[-1]["text"] == guide.ARRIVED


def test_no_answer_repeats_then_gives_up_calmly():
    g = guide.Guide()
    g.on_casualties([CASUALTY], now=0)
    t = guide.REPEAT_AFTER_S
    assert texts(g.tick(t)) == [guide.QUESTIONS[0][1]]
    assert texts(g.tick(2 * t)) == [guide.QUESTIONS[0][1]]
    assert texts(g.tick(3 * t)) == [guide.STAY_STILL]
    assert g.summary("c1")["answers"] == {"hear": "none"}
    later = 3 * t + guide.REASSURE_EVERY_S
    assert texts(g.tick(later)) == [guide.CALM_LINES[0]]
    assert g.tick(later + 1) == []


def test_translation_stand_in_counts_as_no_answer():
    g = guide.Guide()
    g.on_casualties([CASUALTY], now=0)
    assert texts(g.hear("c1", "[translation unavailable: gemini off]", now=1)) == [guide.STAY_STILL]


@pytest.mark.parametrize(("question", "text", "answer"), [
    ("hear", "yes", "yes"), ("hear", "Yes, I can hear you.", "yes"), ("bleeding", "no", "no"),
    ("walk", "I don't know", "unsure"), ("walk", "I can't", "no"), ("hurt", "my leg", "yes"),
    ("breathing", "mmm", "unsure"), ("hear", "", "none"),
])
def test_classify(question, text, answer):
    assert guide.classify(question, text)["answer"] == answer


def test_directions_read_turns_relative_to_the_last_leg():
    # east 1 m, north 1 m (left), east 1 m (right), straight on
    path = ([[i, 0, 0] for i in range(21)] + [[20, j, 0] for j in range(1, 21)]
            + [[i, 20, 0] for i in range(21, 41)])
    assert guide.exit_directions(path, RES) == [
        "Walk slowly towards the robot's light, about one metre.",
        "Turn left, then walk about one metre.",
        "Turn right, then walk about one metre.",
        guide.ARRIVED,
    ]
    assert guide.exit_directions([[1, 1, 0]], RES) == [guide.ARRIVED]


def test_casualty_lines_use_the_calm_tts_style(monkeypatch):
    seen = {}

    def fake_speak_text(text, to="operator", allow_device=True, style=None):
        seen.update(text=text, to=to, style=style)
        return {"spoken": False}

    monkeypatch.setattr(speak, "speak_text", fake_speak_text)
    speak.handle_say({"to": "casualty", "intent": "reassure", "text": "Help is coming.",
                      "lang": "auto"})
    assert seen["style"] == speak.CALM_STYLE
    speak.handle_say({"to": "operator", "intent": "reassure", "text": "ok", "lang": "auto"})
    assert seen["style"] is None


def test_start_wires_the_guide_to_the_bus(monkeypatch):
    spoken = []
    monkeypatch.setattr(speak, "handle_say", lambda data: spoken.append(data["text"]))

    class FakeBus:
        def __init__(self):
            self.subs = {}

        def subscribe(self, topic, fn):
            self.subs.setdefault(topic, []).append(fn)

        def publish(self, topic, data):
            for fn in self.subs.get(topic, []):
                fn(data)

    async def run():
        bus = FakeBus()
        info = await voice.start(bus)
        assert info["guide"] is True
        assert {"map/cells", "map/casualties", "route/proposed", "route/verified",
                "world/change"} <= set(bus.subs)
        bus.publish("map/casualties", [CASUALTY])
        for _ in range(50):
            if len(spoken) >= 2:
                break
            await asyncio.sleep(0.01)

    asyncio.run(run())
    assert spoken[:2] == [guide.GREETING, guide.QUESTIONS[0][1]]
    assert voice.GUIDE.summary("c1")["phase"] == "questions"


def test_guide_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("VOICE_GUIDE", "0")

    class FakeBus:
        def __init__(self):
            self.topics = []

        def subscribe(self, topic, fn):
            self.topics.append(topic)

    bus = FakeBus()
    info = asyncio.run(voice.start(bus))
    assert info["guide"] is False and bus.topics == ["say"]
