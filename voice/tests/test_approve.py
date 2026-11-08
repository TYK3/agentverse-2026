"""G7 checks: spoken "approve" / "hold" answers the planner's gate; off mode leaves it to the button."""

import asyncio
import json

import pytest

from voice import approve, operator

REQ = {"id": "g4", "kind": "risky_move", "summary": "enter room 3 past rubble b11", "route": "r3"}


class Bus:
    def __init__(self):
        self.subs, self.sent = {}, []

    def subscribe(self, topic, fn):
        self.subs.setdefault(topic, []).append(fn)

    async def publish(self, topic, data):
        self.sent.append((topic, data))
        for fn in self.subs.get(topic, []):
            r = fn(data)
            if asyncio.iscoroutine(r):
                await r

    def of(self, topic):
        return [d for t, d in self.sent if t == topic]


class Result:
    def __init__(self, text):
        self.text = text


class Gem:
    """coord/gem.py's surface that approve.py uses; `reply` is what the model says."""

    class GeminiOff(Exception):
        pass

    def __init__(self, mode="live", reply='{"decision": "approve"}', fail=None):
        self.MODE, self.reply, self.fail = mode, reply, fail
        self.calls, self.stand_ins = [], []

    def ask_with_receipt(self, model_key, prompt, thinking="medium", feature="?", route=None, **kw):
        self.calls.append((model_key, feature, route, prompt))
        if self.MODE == "off":
            raise Gem.GeminiOff()
        if self.fail:
            raise self.fail
        return Result(self.reply)

    def mark_stand_in(self, feature):
        self.stand_ins.append(feature)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def setup(gem, timeout_s=60.0):
    bus, clock = Bus(), Clock()
    a = approve.attach(bus, timeout_s=timeout_s, clock=clock, gem=gem)
    asyncio.run(bus.publish("gate/request", REQ))
    return bus, a, clock


def say(a, text):
    return asyncio.run(a.heard(text))


def test_approve_sends_an_approved_answer_once():
    gem = Gem()
    bus, a, _ = setup(gem)
    assert say(a, "Approve, go ahead.") == {"id": "g4", "approved": True, "by": "operator"}
    assert bus.of("gate/answer") == [{"id": "g4", "approved": True, "by": "operator"}]
    assert gem.calls[0][:3] == ("fast_router", "spoken_approval", "r3")       # via coord/gem.py, linked to r3
    assert say(a, "approve") is None and len(bus.of("gate/answer")) == 1      # consumed


def test_hold_sends_a_refusal_so_the_robot_stays_put():
    bus, a, _ = setup(Gem(reply='{"decision": "hold"}'))
    assert say(a, "hold on, wait") == {"id": "g4", "approved": False, "by": "operator"}
    assert bus.of("gate/answer")[-1]["approved"] is False


def test_gemini_alone_never_approves():
    bus, a, _ = setup(Gem(reply='{"decision": "approve"}'))
    assert say(a, "don't approve that") == {"id": "g4", "approved": False, "by": "operator"}   # said hold
    bus, a, _ = setup(Gem(reply='{"decision": "none"}'))
    assert say(a, "yes") is None and not bus.of("gate/answer")                 # model unsure: no answer
    bus, a, _ = setup(Gem(reply="not json"))
    assert say(a, "approve") is None and not bus.of("gate/answer")


def test_hold_wins_if_either_says_hold():
    _bus, a, _ = setup(Gem(reply='{"decision": "hold"}'))
    assert say(a, "yes go") == {"id": "g4", "approved": False, "by": "operator"}


def test_model_failure_still_honours_a_spoken_hold_but_never_approves():
    bus, a, _ = setup(Gem(fail=RuntimeError("cap reached")))
    assert say(a, "approve") is None and not bus.of("gate/answer")
    assert say(a, "stop, hold") == {"id": "g4", "approved": False, "by": "operator"}


def test_timeout_drops_the_request_and_sends_nothing():
    bus, a, clock = setup(Gem(), timeout_s=60.0)
    clock.now = 61.0
    assert say(a, "approve") is None
    assert not bus.of("gate/answer") and ("timed_out", "g4") in a.log
    assert say(a, "approve") is None                                          # nothing pending any more


def test_off_mode_falls_back_to_the_button():
    gem = Gem(mode="off")
    bus, a, _ = setup(gem)
    assert say(a, "approve") is None and say(a, "hold") is None
    assert not bus.of("gate/answer") and not gem.calls and gem.stand_ins == ["spoken_approval"] * 2
    asyncio.run(bus.publish("gate/answer", {"id": "g4", "approved": True, "by": "operator"}))   # the button
    assert a.pending is None


def test_button_first_means_voice_does_not_answer_again():
    bus, a, _ = setup(Gem())
    asyncio.run(bus.publish("gate/answer", {"id": "g4", "approved": True, "by": "operator"}))
    assert say(a, "approve") is None and len(bus.of("gate/answer")) == 1


def test_ordinary_commands_pass_through():
    bus, a, _ = setup(Gem())
    assert say(a, "send water to the back room") is None and a.pending is not None
    bus = Bus()
    a = approve.attach(bus, gem=Gem())
    assert say(a, "approve") is None                                          # no gate pending


def test_operator_turn_answers_the_gate_instead_of_a_command(monkeypatch):
    bus, _a, _ = setup(Gem())
    published = []

    async def fake_publish(*args, **kw):
        published.append(args)
        return {"text": "?"}

    monkeypatch.setattr(operator.command, "publish", fake_publish)
    out = asyncio.run(operator.handle_reply(bus, json.dumps({"goal": "stop"}), "approve"))
    assert out is None and not published and bus.of("gate/answer")[-1]["approved"] is True


def test_the_robot_moves_only_after_the_spoken_approve():
    """End to end with the real planner loop: gate/request, nothing moves, "approve", then it moves."""
    tl = pytest.importorskip("planner.tests.test_loop")
    bus, _lp, _ = tl.setup(casualty={**tl.CASUALTY, "confidence": 0.3})
    a = approve.attach(bus, gem=Gem())
    tl.verify(bus, "r1", True)
    req = bus.of("gate/request")[-1]
    assert a.pending[0]["id"] == req["id"] and not bus.of("responder/action")
    say(a, "approve")
    assert bus.of("responder/action")[-1]["route"] == "r1"
