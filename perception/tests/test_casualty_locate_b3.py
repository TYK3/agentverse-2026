"""LOCATE-B3-TEST: localize the B3 casualty from real Scout sensor frames.

Fixed survey waypoints isolate sensing/fusion from autonomous navigation. Only
B3 frames enter a fresh detector: its local track c1 is checked against sim
casualty c3 only in the final accuracy assertion. No truth coordinates or labels
steer the survey or enter perception. Camera rendering and model calls are off.
"""

import math

from perception.casualties import Casualties
from sim.levels import LevelWorld, max_jump


def test_scout_locates_b3_casualty_from_own_thermal_and_sound():
    world = LevelWorld(seed=0, render=False)
    casualties = Casualties(vision_on=False)
    assert casualties.message() == []

    # Drive real ramps through every floor, then survey B3 from several poses.
    # These fixed navigation targets do not depend on casualty truth or output.
    waypoints = [
        (1.2, 2.1, 0.6), (3.8, 2.1, 0.0), (3.8, 0.3, 0.0),
        (1.2, 0.3, -0.6), (0.6, 0.3, -0.6), (0.6, 1.5, -0.6),
        (1.8, 1.5, -0.6), (1.8, 2.1, -0.6), (4.8, 2.1, -1.2),
        (4.8, 0.3, -1.2), (2.1, 0.3, -1.8), (2.1, 1.6, -1.8),
        (0.8, 1.6, -1.8), (0.8, 0.6, -1.8), (0.3, 0.6, -1.8),
        (0.3, 1.5, -1.8),
    ]
    frames = 0
    visited = [world.level()]
    for target in waypoints:
        world.goto({"target": list(target), "reason": "fixed B3 sensor survey"})
        for tick in range(150):  # bounded at 15 sim seconds per leg; no sleeps
            world.tick(0.1)
            level = world.level()
            if level not in ("ramp", visited[-1]):
                visited.append(level)
            if level == "B3" and tick % 3 == 0:
                casualties.on_sensors(world.sensors_message(camera=False))
                frames += 1
                # Foreground range guesses must not leave duplicate ghost tracks.
                assert [c["id"] for c in casualties.message()] in ([], ["c1"])
            if world.state != "moving":
                break
        assert world.state == "arrived", (target, world.state, world.pos)

    assert visited == ["L1", "ground", "B1", "B2", "B3"]
    assert world.level() == "B3"
    assert max_jump(world.trace) < 0.035
    assert frames >= 30
    result = casualties.message()
    assert [c["id"] for c in result] == ["c1"], result
    casualty = result[0]
    assert set(casualty["clues"]) == {"thermal", "sound"}
    assert 0.7 <= casualty["confidence"] <= 1.0
    assert -1.8 < casualty["pos"][2] < -1.2  # B3, not B2 or flattened z
    assert math.dist(
        casualty["pos"], world.d.geom_xpos[world.m.geom("c3_g").id]
    ) < 0.25, casualty  # simulation truth is an independent oracle only
    assert casualty["vitals"]["simulated"] is True
