"""L2 checks: the Scout calls out, listens for tapping, moves, listens again and locates the casualty."""

import math

import numpy as np
import pytest

from perception import listen
from perception.grid import Grid

CASUALTY = (2.0, 1.0)


def frame(pos, yaw=0.0, level=0.0, motion="idle", rng=None, casualty=CASUALTY, noise_deg=3.0):
    rng = rng or np.random.default_rng(0)
    bearing = math.degrees(math.atan2(casualty[1] - pos[1], casualty[0] - pos[0]) - yaw)
    bearing += rng.normal(0.0, noise_deg)
    bearing = (bearing + 180.0) % 360.0 - 180.0
    return {"pose": {"pos": [pos[0], pos[1], 0.075], "yaw": yaw},
            "acoustic": {"bearing": round(bearing, 1), "level": level}, "motion": {"state": motion}}


def run_dialogue(listener, start, tapping=True, rng=None, steps=400):
    """Drive a listener with a perfect Scout: it arrives at every scout/goto target at once."""
    rng = rng or np.random.default_rng(1)
    pos, t, out, tapping_until = start, 0.0, [], -1.0
    motion = "idle"
    for _ in range(steps):
        level = 0.6 if t < tapping_until else 0.1
        msgs = listener.on_sensors(frame(pos, level=level, motion=motion, rng=rng), t)
        motion = "idle"
        for topic, payload in msgs:
            out.append((round(t, 1), topic, payload))
            if topic == "say" and tapping:
                tapping_until = t + 1.0 + listen.LISTEN_S
            if topic == "scout/goto":
                pos, motion = tuple(payload["target"][:2]), "arrived"
        t = round(t + 0.1, 1)
        if listener.estimate and listener.state == "idle":
            break
    return out


def test_call_listen_move_listen_locate():
    lis = listen.Listener()
    out = run_dialogue(lis, (0.6, 0.6))
    topics = [topic for _, topic, _ in out]
    assert topics == ["say", "scout/goto", "say", "say"]
    assert out[0][2]["text"] == listen.CALL and out[0][2]["to"] == "casualty"
    assert out[2][2]["text"] == listen.CALL_AGAIN and out[3][2]["text"] == listen.FOUND
    goto = out[1][2]
    assert math.dist(goto["target"][:2], (0.6, 0.6)) == pytest.approx(listen.SPOT_M, abs=1e-3)
    assert "2nd spot" in goto["reason"]
    est = lis.estimate
    assert math.dist(est["pos"], CASUALTY) < 0.3 and 0 < est["radius_m"] < 0.6
    assert est["spots"] == 2 and est["clues"] == ["sound"]


def test_no_tapping_means_no_move_and_a_cooldown():
    lis = listen.Listener()
    out = run_dialogue(lis, (0.6, 0.6), tapping=False, steps=60)  # one call, no taps
    assert [p["text"] for _, topic, p in out if topic == "say"][:2] == [listen.CALL, listen.NO_TAP]
    assert not [o for o in out if o[1] == "scout/goto"]
    assert lis.estimate is None
    # It does not call again straight away.
    assert lis.on_sensors(frame((0.6, 0.6), level=0.5), out[1][0] + 1) == []
    assert lis.on_sensors(frame((0.6, 0.6), level=0.5), out[1][0] + listen.RETRY_S + 0.1)[0][0] == "say"


def test_silence_starts_nothing():
    lis = listen.Listener()
    assert lis.on_sensors(frame((0, 0), level=0.02), 0.0) == []
    assert lis.state == "idle" and not lis.active


def free_grid(xs, ys):
    g = Grid()
    for x in xs:
        for y in ys:
            g.free((math.floor(x / g.res), math.floor(y / g.res), 1))
    return g


def test_listening_spot_is_a_seen_free_cell():
    # Only the side y < 0.6 of the first bearing (which points about +x) is mapped free.
    xs = np.arange(-0.5, 1.5, 0.05)
    g = free_grid(xs, np.arange(-1.0, 0.65, 0.05))
    lis = listen.Listener(g)
    lis.pose = ([0.6, 0.6, 0.075], 0.0)
    lis.rays = [((0.6, 0.6), 0.0)]
    spot = lis._spot()
    assert spot is not None and spot[1] < 0.6
    unmapped = listen.Listener(Grid())  # nothing seen yet: no spot is trusted
    unmapped.pose, unmapped.rays = lis.pose, lis.rays
    assert unmapped._spot() is None


def test_intersect_and_uncertainty():
    x = listen.intersect((0, 0), math.radians(45), (2, 0), math.radians(135))
    assert np.allclose(x, (1, 1))
    assert listen.intersect((0, 0), 0.0, (0, 1), 0.0) is None          # parallel
    assert listen.intersect((0, 0), math.pi, (2, 0), 0.0) is None      # behind
    sharp = listen.uncertainty((0, 0), (2, 0), (1, 1), math.radians(90))
    shallow = listen.uncertainty((0, 0), (2, 0), (1, 1), math.radians(20))
    assert shallow > 2 * sharp


RELOOK = {"target": [0.2, -0.3, 0.075], "reason": "re-look to re-earn move permission on route r2"}


def _listen_until_move_due(lis, pos=(0.6, 0.6)):
    """Call, hear tapping for one window; returns (t, messages) at the moment the 2nd spot is due."""
    rng, t, out = np.random.default_rng(1), 0.0, []
    out += lis.on_sensors(frame(pos, level=0.6, rng=rng), t)        # heard -> call
    lis.on_goto(RELOOK, 0.5)                                         # the permit planner takes the Scout
    while t < listen.LISTEN_S + 0.2:
        t = round(t + 0.1, 1)
        out += lis.on_sensors(frame(pos, level=0.6, rng=rng), t)
    return t, out


def test_second_spot_waits_for_a_permit_relook_then_goes():
    lis = listen.Listener()
    t, out = _listen_until_move_due(lis)
    assert [topic for topic, _ in out] == ["say"], "no 2nd-spot goto while the re-look has the Scout"
    assert lis.state == "waiting"
    assert lis.on_sensors(frame((0.4, 0.2)), t + 1) == []           # still driving to the re-look
    moved = lis.on_sensors(frame((0.2, -0.3), motion="arrived"), t + 2)   # re-look reached
    assert [topic for topic, _ in moved] == ["scout/goto"] and moved[0][1]["reason"].startswith(listen.OWN)


def test_a_relook_that_never_clears_ends_the_dialogue_without_overriding_it():
    lis = listen.Listener()
    t, _ = _listen_until_move_due(lis)
    for k in range(0, int(listen.WAIT_MAX_S), 8):                    # the permit re-sends its re-look
        lis.on_goto(RELOOK, t + k)
        assert lis.on_sensors(frame((0.4, 0.2)), t + k + 0.1) == []
    out = lis.on_sensors(frame((0.4, 0.2)), t + listen.WAIT_MAX_S + 0.1)
    assert [topic for topic, _ in out] == ["say"] and out[0][1]["text"] == listen.FOUND
    assert lis.state == "idle" and all(topic != "scout/goto" for topic, _ in out)


def test_its_own_goto_does_not_make_it_wait():
    lis = listen.Listener()
    lis.on_goto({"target": [1.0, 1.0, 0.075], "reason": "listen again from a 2nd spot: tapping heard"}, 0.0)
    assert not lis._scout_busy(0.1)
