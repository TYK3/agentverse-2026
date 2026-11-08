"""LOCATE-SEEDS: real B1 sensor localization across independent acoustic-noise seeds.

Fixed survey navigation isolates localization from autonomous route discovery.
Only genuine LevelWorld sensor frames enter perception; casualty truth appears
only in the final accuracy assertion. No renderer or remote model is needed.
"""

import math

import pytest

from perception.casualties import Casualties
from sim.levels import LevelWorld, max_jump


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 23])
def test_real_b1_localization_survives_sensor_noise_seeds(seed):
    world = LevelWorld(seed=seed, render=False)
    casualties = Casualties(vision_on=False)
    assert casualties.message() == []

    # The same survey for every seed, independent of casualty truth and output.
    # Travel through the real ramps first; only B1 frames go to this detector.
    waypoints = [
        (1.2, 2.1, 0.6), (3.8, 2.1, 0.0), (3.8, 0.3, 0.0),
        (1.2, 0.3, -0.6), (0.6, 0.3, -0.6), (0.6, 1.5, -0.6),
        (1.5, 1.5, -0.6), (0.8, 1.5, -0.6), (0.8, 0.6, -0.6),
        (0.3, 0.6, -0.6), (0.3, 1.5, -0.6),
    ]
    frames = 0
    for target in waypoints:
        world.goto({"target": list(target), "reason": "fixed B1 localization seed survey"})
        for tick in range(150):
            world.tick(0.1)
            if world.level() == "B1" and tick % 3 == 0:
                casualties.on_sensors(world.sensors_message(camera=False))
                frames += 1
                assert [c["id"] for c in casualties.message()] in ([], ["c1"]), seed
            if world.state != "moving":
                break
        assert world.state == "arrived", (seed, target, world.state, world.pos)

    assert world.level() == "B1"
    assert max_jump(world.trace) < 0.035
    assert frames >= 30
    result = casualties.message()
    assert [c["id"] for c in result] == ["c1"], (seed, result)
    casualty = result[0]
    assert set(casualty["clues"]) == {"thermal", "sound"}, (seed, casualty)
    assert 0.7 <= casualty["confidence"] <= 1.0, (seed, casualty)
    assert -0.6 < casualty["pos"][2] < 0.0
    assert math.dist(
        casualty["pos"], world.d.geom_xpos[world.m.geom("c1_g").id]
    ) < 0.25, (seed, casualty)
    assert casualty["vitals"]["simulated"] is True
