"""CONTACT-HAS-RANGE: every casualty contact happens within sensor range of the casualty.

voice/contact.py talks to a casualty through the Scout's speaker and hears them back as
`casualty/reply`. The sim (sim/world.py on_say) lets a casualty hear the Scout only within HEAR_CALL_M
and at most two walls away. So every `casualty/contact` the robot reports, and every line it says to
that casualty, should come while the Scout is in that range. Otherwise the contact is with nobody: no
answer is possible, and "unresponsive" says something about the casualty that was never measured.

Real World (backup scene, c1 calling out at full voice) and the real Contact core; no fakes. The Scout
is placed with World._set_pose, as sim/tests/test_casualty_reply.py does. Contact gets what the bus
gives it: c1's pos on `map/casualties` and the Scout's pose from `sensors/scout`.

Was a gap (CONTACT-RANGE-FIX): Contact started with the most confident casualty wherever the Scout
was. From 7.2 m away (HEAR_CALL_M is 6.0) it talked to c1, heard nothing and reported a responsive
casualty as "unresponsive". (The Scout's own start is not used: it is behind three walls at first,
but settling rubble brings c1 within two walls after about 10 s.)

Run: GEMINI_MODE=off uv run --no-project --with mujoco --with numpy --with pytest \
         python -m pytest tools/tests/test_contact_has_range.py -q
"""

import numpy as np
import pytest

pytest.importorskip("mujoco")

from sim import sensors
from sim.world import HEAR_CALL_M, World
from voice import contact as C

NEAR_C1 = ((1.6, 0.73), 0.0)    # in room 3 with c1 (sim/tests/test_casualty_reply.py)
FAR = ((-4.0, -3.0), 0.0)       # outside, 7.2 m from c1: past HEAR_CALL_M whatever the rubble does


def in_range(w, name):
    """Whether casualty `name` can hear the Scout now: the sim's own rule in World.on_say."""
    geom = next(g for n, g, _ in w.casualties if n == name)
    origin, casualty = w.sensor_origin, w.d.geom_xpos[geom].copy()
    if float(np.linalg.norm((casualty - origin)[:2])) > HEAR_CALL_M:
        return False
    hit, _ = sensors.first_hit(w.m, w.d, origin, casualty, w.scout)
    return hit == geom or sensors.walls_between(w.m, w.d, origin, casualty, w.scout, geom) <= 2


def c1_pos(w):
    geom = next(g for n, g, _ in w.casualties if n == "c1")
    return [round(float(v), 3) for v in w.d.geom_xpos[geom]]


def converse(w, pose=None, seconds=80.0, moves=None):
    """Run one contact with c1 against the scene. `moves` maps a step (0.5 s each) to a pose to put the
    Scout at. Returns [(topic, data, c1 in range)] for every `say` and `casualty/contact` published,
    and the final session (None if no contact started)."""
    if pose:
        w._set_pose(*pose)
    clock = {"t": 0.0}
    c = C.Contact(gem=False, clock=lambda: clock["t"])
    out = c.on_scout(w.sensor_origin.tolist(), now=0.0)
    out += c.on_casualties([{"id": "c1", "confidence": 0.9, "pos": c1_pos(w)}], now=0.0)
    seen = []
    for step in range(round(seconds / 0.5)):
        if moves and step in moves:
            w._set_pose(*moves[step])
            out += c.on_scout(w.sensor_origin.tolist(), now=w.t)
        for topic, data in out:
            if topic in ("say", "casualty/contact"):
                seen.append((topic, data, in_range(w, "c1")))
            if topic == "say":
                w.on_say(data)
        replies = []
        for _ in range(5):
            replies += [d for t, d in w.tick(0.1) if t == "casualty/reply"]
        clock["t"] = w.t
        out = []
        for r in replies:
            out += c.hear(r)
        out += c.tick()
        if "c1" in c.sessions and c.sessions["c1"].status != "talking" and not out:
            break
    return seen, c.sessions.get("c1")


def test_in_range_rule_matches_the_sim():
    w = World(render=False)
    w._set_pose(*FAR)
    assert not in_range(w, "c1")
    w._set_pose(*NEAR_C1)
    assert in_range(w, "c1")


def test_a_contact_in_range_is_answered_and_every_line_is_in_range():
    seen, s = converse(World(render=False), NEAR_C1)
    assert s.status == "done", (s.status, s.asked)
    assert [d["status"] for t, d, _ in seen if t == "casualty/contact"][-1] == "done"
    assert all(ok for _, _, ok in seen), [(t, d.get("text") or d.get("status")) for t, d, ok in seen if not ok]


def test_an_unresponsive_verdict_needs_the_casualty_in_range_to_mean_anything():
    """Guard for the xfail below: from in range, a voiced c1 is never reported unresponsive."""
    _, s = converse(World(render=False), NEAR_C1)
    assert s.status != "unresponsive"


def test_every_contact_is_within_sensor_range():
    seen, s = converse(World(render=False), FAR, seconds=40.0)  # the Scout stays 7.2 m away
    out_of_range = [(t, d.get("status") or d.get("text")) for t, d, ok in seen if not ok]
    assert out_of_range == [], f"published out of c1's earshot: {out_of_range}; final {s and s.status}"
    assert s is None, "no contact may start with a casualty who cannot hear the Scout"


def test_the_contact_starts_once_the_scout_comes_in_range():
    seen, s = converse(World(render=False), FAR, moves={20: NEAR_C1})   # arrives at 10 s
    assert s is not None and s.status == "done", s and (s.status, s.asked)
    assert s.started >= 10.0 - 1e-9
    assert all(ok for _, _, ok in seen)


def test_leaving_range_mid_contact_is_not_unresponsive():
    """The Scout walks off after the first line and comes back: c1 is not called unresponsive."""
    seen, s = converse(World(render=False), NEAR_C1, moves={1: FAR, 80: NEAR_C1})  # away 0.5 s .. 40 s
    assert s.status == "done", (s.status, s.asked)
    assert "unresponsive" not in [d["status"] for t, d, _ in seen if t == "casualty/contact"]
