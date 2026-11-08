"""LOCATE-REAL-TEST: localize c1 using unmodified Scout frames from the real B1 sim.

Fixed survey waypoints exercise sensing/fusion, not autonomous route discovery. No
scene blocks or casualty coordinates enter perception or steer the survey; sim
truth is read only by the final accuracy assertion. Camera/model calls are off.
"""

import math

from perception.casualties import Casualties
from sim.levels import LevelWorld, max_jump


def test_scout_locates_single_c1_from_real_b1_thermal_and_sound():
    world = LevelWorld(seed=0, render=False)
    casualties = Casualties(vision_on=False)
    assert casualties.message() == []

    # Drive the real ramps from L1, then survey B1 from distinct viewpoints.
    # These are navigation targets, never an injected casualty estimate or yaw.
    waypoints = [
        (1.2, 2.1, 0.6), (3.8, 2.1, 0.0), (3.8, 0.3, 0.0),
        (1.2, 0.3, -0.6), (0.6, 0.3, -0.6), (0.6, 1.5, -0.6),
        (1.5, 1.5, -0.6), (0.8, 1.5, -0.6), (0.8, 0.6, -0.6),
        (0.3, 0.6, -0.6), (0.3, 1.5, -0.6),
    ]
    frames = 0
    for target in waypoints:
        world.goto({"target": list(target), "reason": "fixed B1 sensor survey"})
        for tick in range(150):  # bounded at 15 sim seconds per leg; no sleeps
            world.tick(0.1)
            if world.level() == "B1" and tick % 3 == 0:
                frame = world.sensors_message(camera=False)
                casualties.on_sensors(frame)
                frames += 1
                # Foreground LiDAR returns must not leave duplicate ghost tracks.
                assert [c["id"] for c in casualties.message()] in ([], ["c1"])
            if world.state != "moving":
                break
        assert world.state == "arrived", (target, world.state, world.pos)

    assert world.level() == "B1"
    assert max_jump(world.trace) < 0.035  # actual driving, not pose teleportation
    assert frames >= 30
    result = casualties.message()
    assert [c["id"] for c in result] == ["c1"], result
    casualty = result[0]
    assert set(casualty["clues"]) == {"thermal", "sound"}
    assert 0.7 <= casualty["confidence"] <= 1.0
    assert -0.6 < casualty["pos"][2] < 0.0  # retain basement height
    assert math.dist(
        casualty["pos"], world.d.geom_xpos[world.m.geom("c1_g").id]
    ) < 0.25, casualty  # independent sim truth is an oracle only, never input
    assert casualty["vitals"]["simulated"] is True
