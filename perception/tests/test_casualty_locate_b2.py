"""B2-LOCATE-TEST: locate the B2 casualty from real Scout thermal/sound frames.

Fixed survey waypoints test sensing/fusion, not autonomous navigation. This fresh
floor-local detector receives only B2 frames, so its first track is called c1;
it is checked against sim casualty c2 only in the final accuracy assertion. No
truth labels/coordinates enter perception or steer the survey. No rendering.
"""

import math

from perception.casualties import Casualties
from sim.levels import LevelWorld, max_jump


def test_scout_locates_b2_casualty_from_own_thermal_and_sound():
    world = LevelWorld(seed=0, render=False)
    casualties = Casualties(vision_on=False)
    assert casualties.message() == []

    # Drive real ramps from L1 through ground and B1 to B2, then survey B2.
    # Identical fixed navigation irrespective of detections; no truth-based yaw.
    waypoints = [
        (1.2, 2.1, 0.6), (3.8, 2.1, 0.0), (3.8, 0.3, 0.0),
        (1.2, 0.3, -0.6), (0.6, 0.3, -0.6), (0.6, 1.5, -0.6),
        (1.8, 1.5, -0.6), (1.8, 2.1, -0.6), (4.8, 2.1, -1.2),
        (4.8, 1.5, -1.2), (2.7, 1.5, -1.2), (1.3, 1.5, -1.2),
        (0.6, 1.5, -1.2), (0.6, 0.8, -1.2), (1.2, 0.8, -1.2),
        (1.2, 0.3, -1.2), (1.05, 0.3, -1.2), (1.05, 1.5, -1.2),
        (0.3, 1.5, -1.2), (0.3, 0.9, -1.2),
    ]
    frames = 0
    visited = [world.level()]
    for target in waypoints:
        world.goto({"target": list(target), "reason": "fixed B2 sensor survey"})
        for tick in range(150):  # bounded at 15 sim seconds per leg; no sleeps
            world.tick(0.1)
            level = world.level()
            if level not in ("ramp", visited[-1]):
                visited.append(level)
            if level == "B2" and tick % 3 == 0:
                casualties.on_sensors(world.sensors_message(camera=False))
                frames += 1
                assert [c["id"] for c in casualties.message()] in ([], ["c1"])
            if world.state != "moving":
                break
        assert world.state == "arrived", (target, world.state, world.pos)

    assert visited == ["L1", "ground", "B1", "B2"]
    assert world.level() == "B2"
    assert max_jump(world.trace) < 0.035
    assert frames >= 30
    result = casualties.message()
    assert [c["id"] for c in result] == ["c1"], result
    casualty = result[0]
    assert set(casualty["clues"]) == {"thermal", "sound"}
    assert 0.7 <= casualty["confidence"] <= 1.0
    assert -1.2 < casualty["pos"][2] < -0.6  # B2, not B1 or a flattened map
    assert math.dist(
        casualty["pos"], world.d.geom_xpos[world.m.geom("c2_g").id]
    ) < 0.25, casualty  # independent sim truth is an oracle only
    assert casualty["vitals"]["simulated"] is True
