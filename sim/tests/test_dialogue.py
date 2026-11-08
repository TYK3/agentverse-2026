"""L2 in the real sim: the casualty knocks back when called, and the Scout locates them by sound alone."""

import math

import numpy as np

from perception.grid import Grid
from perception.listen import Listener
from sim.world import World


def run(start, seconds=40):
    w = World(render=False)
    w._set_pose(start, 0.0)
    grid, lis, said = Grid(), Listener(Grid()), []
    lis.grid = grid
    for _ in range(round(seconds / 0.1)):
        w.tick(0.1)
        data = w.sensors_message(camera=False)
        grid.add_sensors(data)
        for topic, payload in lis.on_sensors(data, w.t):
            if topic == "say":
                said.append(payload["text"])
                w.on_say(payload)
            else:
                w.goto(payload)
        if lis.estimate and lis.state == "idle":
            break
    return w, lis, said


def test_scout_locates_the_casualty_from_two_tapping_bearings():
    w, lis, said = run([0.6, 0.6])
    casualty = w.d.geom_xpos[w.casualty_geom][:2]  # c1
    assert lis.estimate is not None, lis.log
    assert math.dist(lis.estimate["pos"], casualty) < 0.25
    assert lis.estimate["radius_m"] < 0.6 and lis.estimate["spots"] >= 2
    assert said[0].startswith("Hello?") and said[-1].startswith("I can hear you")


def test_casualty_taps_only_when_the_call_is_heard():
    w = World(render=False)
    w._set_pose([0.6, 0.6], 0.0)
    w.on_say({"to": "operator", "intent": "reassure", "text": "status", "lang": "auto"})
    assert w.tapping == {}  # the operator's lines are not played inside
    w.on_say({"to": "casualty", "intent": "reassure", "text": "tap", "lang": "auto"})
    assert w.tapping and not w.is_tapping()  # reaction time first
    w.tick(1.1)
    assert w.is_tapping()
    loud = np.mean([w.sensors_message(camera=False)["acoustic"]["level"] for _ in range(20)])
    w.tick(6.0)
    assert not w.is_tapping()
    quiet = np.mean([w.sensors_message(camera=False)["acoustic"]["level"] for _ in range(20)])
    assert loud > quiet

    far = World(render=False)
    far._set_pose([-1.0, -2.5], 0.0)  # outside the breach, more than 6 m of rubble away
    far.on_say({"to": "casualty", "intent": "reassure", "text": "tap", "lang": "auto"})
    assert far.tapping == {}
