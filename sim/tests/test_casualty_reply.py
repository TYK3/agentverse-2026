"""G3 checks: a simulated casualty answers the robot in words (casualty/reply), only when they can hear
it, and a whole bounded contact (voice/contact.py) runs against the real scene."""

from sim import persona
from sim.world import REPLY_DELAY_S, World


def ticks(world, seconds):
    out = []
    for _ in range(round(seconds / 0.1)):
        out += world.tick(0.1)
    return [d for t, d in out if t == "casualty/reply"]


def test_casualty_answers_what_was_asked_after_a_short_delay():
    w = World(render=False)
    w._set_pose((1.6, 0.73), 0.0)                  # in room 3 with c1
    w.on_say({"to": "casualty", "intent": "first_aid", "text": "Are you bleeding anywhere?", "lang": "auto"})
    assert ticks(w, REPLY_DELAY_S - 0.2) == []
    got = ticks(w, 0.5)
    assert len(got) == 1 and got[0]["id"] == "c1" and got[0]["source"] == "sim"
    assert got[0]["text"] == persona.answer(persona.persona("c1"), "Are you bleeding anywhere?")
    assert 0 < got[0]["level"] <= 1


def test_two_lines_back_to_back_get_one_answer_to_the_last():
    w = World(render=False)
    w._set_pose((1.6, 0.73), 0.0)
    w.on_say({"to": "casualty", "intent": "first_aid", "text": "Keep the hurt part still.", "lang": "auto"})
    w.on_say({"to": "casualty", "intent": "first_aid", "text": "Are you cold or wet?", "lang": "auto"})
    got = ticks(w, 3)
    assert [g["text"] for g in got] == ["Yes, I'm so cold."]


def test_no_words_from_out_of_earshot_or_to_the_operator():
    w = World(render=False)                        # the Scout starts outside the building, > 2 walls from c1
    w.on_say({"to": "casualty", "intent": "reassure", "text": "Can you hear me?", "lang": "auto"})
    assert ticks(w, 3) == []
    w._set_pose((1.6, 0.73), 0.0)
    w.on_say({"to": "operator", "intent": "reassure", "text": "Can you hear me?", "lang": "auto"})
    assert ticks(w, 3) == []


def test_bounded_contact_runs_end_to_end_against_the_scene():
    from voice import contact as C

    w = World(render=False)
    w._set_pose((1.6, 0.73), 0.0)
    clock = {"t": 0.0}
    c = C.Contact(gem=False, clock=lambda: clock["t"])
    out = c.on_casualties([{"id": "c1", "confidence": 0.9}])
    heard = []
    for _ in range(40):
        for topic, data in out:
            if topic == "say":
                w.on_say(data)
        replies = ticks(w, 2.0)
        clock["t"] = w.t
        out = []
        for r in replies:
            heard.append(r["text"])
            out += c.hear(r)
        out += c.tick()
        if c.sessions["c1"].status != "talking":
            break
    s = c.sessions["c1"]
    assert s.status == "done", (s.status, s.asked)
    assert s.facts["hurt"] == ["leg"] and s.facts["can_move"] is False and s.facts["cold"] is True
    assert "walk" not in s.asked and "care_still" in s.asked
    assert len(s.asked) <= C.MAX_TURNS and len(heard) >= 5
