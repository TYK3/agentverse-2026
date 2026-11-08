"""G3 checks: casualty contact reacts to what it hears, stays inside its bounds, and every Gemini answer
is checked before anything it chose is said."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from voice import contact as C
from voice import firstaid

_spec = importlib.util.spec_from_file_location("persona", Path(__file__).parents[2] / "sim" / "persona.py")
persona = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(persona)   # sim/persona.py without importing the sim package (no MuJoCo here)


def talk(cid, contact=None, interpret=None, max_lines=30):
    """Run a whole contact against the sim persona for `cid`; returns (contact, robot lines)."""
    c = contact or C.Contact(gem=False, clock=lambda: 0.0)
    p = persona.persona(cid)
    t = 0.0
    out = c.on_casualties([{"id": cid, "confidence": 0.9}], now=t)
    lines = []
    for _ in range(max_lines):
        says = [d["text"] for topic, d in out if topic == "say"]
        lines += says
        s = c.sessions[cid]
        if s.status != "talking" or not says:
            break
        t += 2.0
        out = c.hear({"id": cid, "t": t, "text": persona.answer(p, says[-1]), "source": "sim"},
                     interpret=interpret, now=t)
    return c, lines


def moves(c, cid):
    return c.sessions[cid].asked


# ---- reacting, not reading a script --------------------------------------------------------------

def test_broken_leg_gets_keep_still_and_never_a_walk_suggestion():
    c, lines = talk("c1")
    s = c.sessions["c1"]
    assert moves(c, "c1")[:4] == ["hear", "where", "move", "care_still"], moves(c, "c1")
    assert "walk" not in moves(c, "c1"), "never ask someone with a hurt leg to walk"
    assert "care_warm" in moves(c, "c1") and moves(c, "c1").index("care_warm") == moves(c, "c1").index("cold") + 1
    assert s.status == "done" and lines[-1] == C.MOVES["close"][0]
    assert s.facts["hurt"] == ["leg"] and s.facts["can_move"] is False and s.facts["bleeding"] is False
    assert s.facts["cold"] is True and s.facts["responsive"] is True
    assert any("broken" in i for i in s.injuries), s.injuries


def test_bleeding_answer_brings_the_pressure_line_next():
    c, _lines = talk("c2")
    m = moves(c, "c2")
    assert m[m.index("bleeding") + 1] == "care_bleeding", m
    assert c.sessions["c2"].facts["bleeding"] is True


def test_different_casualties_get_different_conversations():
    runs = {cid: moves(talk(cid)[0], cid) for cid in ("c1", "c2", "c3")}
    assert len({tuple(m) for m in runs.values()}) == 3, runs
    assert "care_breathing" in runs["c3"] and "care_breathing" not in runs["c1"]


def test_an_answer_that_says_more_skips_the_questions_it_answered():
    c = C.Contact(gem=False)
    c.on_casualties([{"id": "c9", "confidence": 0.9}], now=0)
    c.hear({"id": "c9", "text": "Yes"}, now=1)
    out = c.hear({"id": "c9", "text": "My arm is bleeding and I'm so cold"}, now=2)
    said = [d["text"] for t, d in out if t == "say"]
    assert said[0] == C.MOVES["care_bleeding"][0]
    s = c.sessions["c9"]
    assert s.facts["bleeding"] is True and s.facts["cold"] is True and s.facts["hurt"] == ["arm"]


# ---- bounds ---------------------------------------------------------------------------------------

def test_silence_repeats_once_then_ends_unresponsive():
    c = C.Contact(gem=False)
    c.on_casualties([{"id": "c1", "confidence": 0.9}], now=0)
    assert c.tick(now=C.REPLY_WAIT_S - 1) == []
    again = c.tick(now=C.REPLY_WAIT_S)
    assert [d["text"] for t, d in again if t == "say"] == [C.MOVES["hear"][0]]
    end = c.tick(now=2 * C.REPLY_WAIT_S)
    contact = [d for t, d in end if t == "casualty/contact"][-1]
    assert contact["status"] == "unresponsive" and c.active is None


def test_turn_and_time_caps():
    c = C.Contact(gem=False)
    c.on_casualties([{"id": "c1", "confidence": 0.9}], now=0)
    for k in range(20):                                    # answers that never settle anything
        c.hear({"id": "c1", "text": "I don't know"}, now=k + 1)
    s = c.sessions["c1"]
    assert s.status == "done" and len(s.asked) <= C.MAX_TURNS
    c2 = C.Contact(gem=False)
    c2.on_casualties([{"id": "c2", "confidence": 0.9}], now=0)
    c2.hear({"id": "c2", "text": "yes"}, now=5)
    out = c2.tick(now=C.MAX_S)
    assert c2.sessions["c2"].status == "done" and any(t == "casualty/contact" for t, _ in out)


def test_low_confidence_casualty_is_not_contacted_and_others_queue():
    c = C.Contact(gem=False)
    assert c.on_casualties([{"id": "c5", "confidence": 0.3}], now=0) == []
    c.on_casualties([{"id": "c1", "confidence": 0.9}, {"id": "c2", "confidence": 0.95}], now=0)
    assert c.active == "c2" and c.queue == ["c1"]
    assert c.hear({"id": "c1", "text": "help!"}, now=1) == [], "only the casualty being talked to is heard"


def test_aftershock_stops_the_contact_with_the_protect_line():
    c = C.Contact(gem=False)
    c.on_casualties([{"id": "c1", "confidence": 0.9}], now=0)
    out = c.on_world_change({"kind": "aftershock", "t": 3, "moved_blocks": []}, now=3)
    assert [d["text"] for t, d in out if t == "say"] == [C.AFTERSHOCK]
    assert c.sessions["c1"].status == "stopped" and c.hear({"id": "c1", "text": "yes"}, now=4) == []


def test_every_line_is_short_plain_and_cited():
    for move, (line, _intent, _asks, cites) in C.MOVES.items():
        assert len(line.split()) <= 20, move
        assert not any(b in line.lower() for b in C.BANNED), move
        if cites:
            assert firstaid.get_step(cites) is not None, f"{move} cites a missing first aid step"


def test_self_care_lines_are_the_cited_steps_own_words():
    """ref FIRSTAID-SOURCES: what the robot says is the cited step's casualty_line, never a drifting copy."""
    for move, (line, intent, asks, cites) in C.MOVES.items():
        if move.startswith("care_"):
            assert asks is None and intent == "first_aid" and cites, move
            assert line == firstaid.casualty_line(cites), move
    assert C.MOVES["care_breathing"][3] == "protect_airway_from_dust"
    assert C.MOVES["care_spine"][3] == "protect_spine" and C.MOVES["care_still"][3] == "keep_limb_still"


def test_neck_pain_gets_keep_head_still_and_is_never_asked_to_move_or_walk():
    c = C.Contact(gem=False)
    c.on_casualties([{"id": "c9", "confidence": 0.9}], now=0)
    c.hear({"id": "c9", "text": "Yes, I can hear you."}, now=1)
    out = c.hear({"id": "c9", "text": "My neck hurts a lot."}, now=2)
    said = [m for m in c.sessions["c9"].asked]
    assert said[:3] == ["hear", "where", "care_spine"], said
    assert C.MOVES["care_spine"][0] in [d["text"] for t, d in out if t == "say"]
    for k, reply in enumerate(["No.", "No, I can breathe.", "No.", "Yes, I'm cold."] * 2, start=3):
        c.hear({"id": "c9", "text": reply}, now=k)
    asked = c.sessions["c9"].asked
    assert "move" not in asked and "walk" not in asked, asked


def test_a_late_answer_picks_an_unresponsive_contact_up_again():
    """ref LATE-REPLY (live run): "Are you hurt?" was answered 36 s later, after the contact had ended as
    unresponsive, so the answer was dropped and no first aid line was ever said."""
    c = C.Contact(gem=False)
    c.on_casualties([{"id": "c1", "confidence": 0.9}], now=0)
    c.hear({"id": "c1", "text": "Yes, I can hear you."}, now=1)            # -> "where"
    c.tick(now=1 + C.REPLY_WAIT_S)                                          # repeat
    c.tick(now=1 + 2 * C.REPLY_WAIT_S)                                      # second silence
    s = c.sessions["c1"]
    assert s.status == "unresponsive" and c.active is None
    out = c.hear({"id": "c1", "text": "Yes, my left leg. I think it's broken."}, now=40)
    assert s.status == "talking" and c.active == "c1"
    assert s.facts["hurt"] == ["leg"] and s.injuries
    assert any(t == "log/decision" and d["outcome"] == "resumed" for t, d in out)
    assert s.asked[-1] == "move", s.asked                                    # the conversation goes on
    assert c.tick(now=41) == [], "no instant repeat right after picking up (live run: a stale timer did)"
    c.tick(now=40 + C.REPLY_WAIT_S)
    c.tick(now=40 + 2 * C.REPLY_WAIT_S)
    assert s.status == "unresponsive"
    c.hear({"id": "c1", "text": "My arms, yes. Not my left leg, it hurts too much."}, now=90)
    assert s.revived == 2 and s.facts["can_move"] is False and "care_still" in s.asked, s.asked


def test_no_pick_up_after_the_turn_cap():
    c = C.Contact(gem=False)
    c.on_casualties([{"id": "c1", "confidence": 0.9}], now=0)
    s = c.sessions["c1"]
    s.asked += ["where"] * (C.MAX_TURNS - len(s.asked))
    s.status, c.active = "unresponsive", None
    assert c.hear({"id": "c1", "text": "Yes, my leg."}, now=50) == [], "MAX_TURNS still bounds the contact"


def test_a_late_answer_does_not_cut_into_another_contact():
    c = C.Contact(gem=False)
    c.on_casualties([{"id": "c1", "confidence": 0.9}, {"id": "c2", "confidence": 0.8}], now=0)
    c.tick(now=C.REPLY_WAIT_S)
    c.tick(now=2 * C.REPLY_WAIT_S)
    assert c.sessions["c1"].status == "unresponsive" and c.active == "c2"
    assert c.hear({"id": "c1", "text": "Yes, I can hear you."}, now=25) == []
    assert c.active == "c2"


# ---- Gemini, bounded --------------------------------------------------------------------------------

class FakeGem:
    def __init__(self, answer):
        self.MODEL_IDS = {"fast_subagent": "gemini-3.8-flash"}
        self.answer, self.calls, self.stand_ins = answer, [], set()

    def ask_with_receipt(self, key, prompt, thinking="medium", feature="?", **kw):
        self.calls.append((key, feature, prompt))
        if isinstance(self.answer, Exception):
            raise self.answer
        return SimpleNamespace(text=self.answer, receipt={"id": f"gem-{len(self.calls):032x}"})

    def mark_stand_in(self, feature):
        self.stand_ins.add(feature)


def _first_turn(gem):
    c = C.Contact(gem=gem)
    c.on_casualties([{"id": "c1", "confidence": 0.9}], now=0)
    s = c.sessions["c1"]
    got = c.interpret_with_gemini(s, "yes, my leg")
    return c, s, got


def test_gemini_picks_the_move_and_adds_a_short_ack_with_a_receipt():
    gem = FakeGem(json.dumps({"facts": {"hurt": ["leg"], "responsive": True}, "next": "move",
                              "ack": "I hear you, your leg hurts"}))
    c, _s, got = _first_turn(gem)
    answer, model, receipt = got
    assert answer["next"] == "move" and model == "gemini-3.8-flash" and receipt.startswith("gem-")
    out = c.hear({"id": "c1", "text": "yes, my leg"}, interpret=lambda *_: got, now=1)
    said = [d["text"] for t, d in out if t == "say"]
    assert said == ["I hear you, your leg hurts. " + C.MOVES["move"][0]]
    contact = [d for t, d in out if t == "casualty/contact"][-1]
    assert contact["receipts"] == [receipt]
    assert "Casualty just said" in gem.calls[0][2] and gem.calls[0][1] == "casualty_contact"


@pytest.mark.parametrize("raw", [
    json.dumps({"facts": {}, "next": "give_painkillers", "ack": ""}),              # not an allowed move
    json.dumps({"facts": {}, "next": "hear", "ack": ""}),                          # already said
    "sure! ask about the leg",                                                      # not JSON
])
def test_out_of_bounds_gemini_answers_fall_back_to_the_local_reader(raw):
    _c, _s, (answer, model, receipt) = _first_turn(FakeGem(raw))
    assert answer is None and "out of bounds" in model and receipt


def test_advice_or_long_acks_and_unknown_fact_keys_are_dropped():
    gem = FakeGem(json.dumps({"facts": {"diagnosis": "fracture", "bleeding": False}, "next": "bleeding",
                              "ack": "You have a fracture, take a pill"}))
    _c, _s, (answer, _m, _r) = _first_turn(gem)
    assert answer == {"facts": {"bleeding": False}, "next": "bleeding", "ack": ""}
    long = FakeGem(json.dumps({"facts": {}, "next": "bleeding", "ack": " ".join(["calm"] * 20)}))
    assert _first_turn(long)[2][0]["ack"] == ""


def test_gemini_off_uses_the_local_reader_and_marks_the_stand_in():
    class GeminiOff(Exception):
        pass
    gem = FakeGem(GeminiOff("casualty_contact"))
    _c, _s, got = _first_turn(gem)
    assert got == (None, C.MODEL, None) and gem.stand_ins == {"casualty_contact"}


# ---- contract ---------------------------------------------------------------------------------------

def test_every_message_matches_the_contract():
    messages = pytest.importorskip("coord.messages")
    c = C.Contact(gem=False, clock=lambda: 0.0)
    out = c.on_casualties([{"id": "c1", "confidence": 0.9}], now=0)
    for cid in ("c1",):
        p = persona.persona(cid)
        for k in range(12):
            says = [d["text"] for t, d in out if t == "say"]
            for topic, data in out:
                messages.validate_payload(topic, data)
            if not says or c.sessions[cid].status != "talking":
                break
            out = c.hear({"id": cid, "t": k, "text": persona.answer(p, says[-1]), "source": "sim"}, now=k)
    assert c.summary("c1")["status"] == "done"


# ---- wired to a bus -------------------------------------------------------------------------------

class AnsweringBus:
    """A tiny async bus; the casualty (sim persona) answers every say to them on casualty/reply."""

    def __init__(self, cid="c1", answers=True):
        self.subs, self.sent, self.cid, self.answers = {}, [], cid, answers

    def subscribe(self, topic, fn):
        self.subs.setdefault(topic, []).append(fn)

    async def publish(self, topic, data):
        self.sent.append((topic, data))
        for fn in self.subs.get(topic, []):
            await fn(data)
        if topic == "say" and data["to"] == "casualty" and self.answers and "?" in data["text"]:
            text = persona.answer(persona.persona(self.cid), data["text"])
            await self.publish("casualty/reply", {"id": self.cid, "t": 0, "text": text, "source": "sim"})


def test_start_runs_a_contact_over_the_bus():
    import asyncio

    async def go():
        bus = AnsweringBus()
        c = C.start(bus, gem=False)
        await bus.publish("map/casualties", [{"id": "c1", "confidence": 0.9}])
        return bus, c

    bus, c = asyncio.run(go())
    assert c.sessions["c1"].status == "done"
    topics = {t for t, _ in bus.sent}
    assert {"say", "casualty/reply", "casualty/contact", "log/decision"} <= topics


def test_start_times_out_a_silent_casualty(monkeypatch):
    import asyncio
    monkeypatch.setattr(C, "REPLY_WAIT_S", 0.05)

    async def go():
        bus = AnsweringBus(answers=False)
        c = C.start(bus, gem=False)
        await bus.publish("map/casualties", [{"id": "c1", "confidence": 0.9}])
        await asyncio.sleep(0.4)
        return c

    c = asyncio.run(go())
    assert c.sessions["c1"].status == "unresponsive"
