"""CONTACT-HAS-RANGE: every casualty contact happens within sensor range of the casualty.

voice/contact.py talks to a casualty through the Scout's speaker and hears them back as
`casualty/reply`. The sim (sim/world.py on_say) lets a casualty hear the Scout only within HEAR_CALL_M
and at most two walls away. So every `casualty/contact` the robot reports, and every line it says to
that casualty, should come while the Scout is in that range. Otherwise the contact is with nobody: no
answer is possible, and "unresponsive" says something about the casualty that was never measured.

Real World (backup scene, c1 calling out at full voice) and the real Contact core; no fakes. The Scout
is placed with World._set_pose, as sim/tests/test_casualty_reply.py does.

Known gap (strict xfail): Contact starts with the most confident casualty on `map/casualties` wherever
the Scout is. From 7.2 m away (HEAR_CALL_M is 6.0) it talks to c1, hears nothing and reports a
responsive casualty as "unresponsive". (The Scout's own start is not used: it is behind three walls at
first, but settling rubble brings c1 within two walls after about 10 s.)

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


def converse(w, pose=None, seconds=80.0):
    """Run one contact with c1 against the scene. Returns [(topic, data, c1 in range)] for every
    `say` and `casualty/contact` published, and the final session."""
    if pose:
        w._set_pose(*pose)
    clock = {"t": 0.0}
    c = C.Contact(gem=False, clock=lambda: clock["t"])
    out = c.on_casualties([{"id": "c1", "confidence": 0.9}], now=0.0)
    seen = []
    for _ in range(round(seconds / 0.5)):
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
        if c.sessions["c1"].status != "talking" and not out:
            break
    return seen, c.sessions["c1"]


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


@pytest.mark.xfail(strict=True, reason="CONTACT-HAS-RANGE: voice/contact.py starts a contact from "
                   "map/casualties wherever the Scout is; out of earshot it reports c1 unresponsive")
def test_every_contact_is_within_sensor_range():
    seen, s = converse(World(render=False), FAR)  # the Scout stays 7.2 m away, out of c1's earshot
    out_of_range = [(t, d.get("status") or d.get("text")) for t, d, ok in seen if not ok]
    assert out_of_range == [], f"published out of c1's earshot: {out_of_range}; final status {s.status}"
