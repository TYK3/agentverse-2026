"""T04 checks: the Scout drives to scout/goto targets, refuses walls, and streams sensors/scout."""

import asyncio
import json
import time

import numpy as np
import pytest

import sim
from sim import sensors
from sim.world import World


@pytest.fixture
def world():
    return World(render=False)


def _drive(world, target, seconds):
    world.goto({"target": target + [0.075], "reason": "test"})
    for _ in range(round(seconds * 10)):
        world.tick(0.1)
        if world.state != "moving":
            break


def test_drives_to_target_at_speed(world):
    start = world.pos[:2].copy()
    world.goto({"target": [-0.5, -0.3, 0.075], "reason": "enter"})
    world.tick(1.0)
    assert np.linalg.norm(world.pos[:2] - start) == pytest.approx(0.3, abs=1e-6)
    _drive(world, [-0.5, -0.3], 10)
    assert world.state == "arrived"
    assert np.linalg.norm(world.pos[:2] - [-0.5, -0.3]) < 0.03


def test_refuses_to_drive_through_a_wall(world):
    _drive(world, [-0.5, -0.3], 10)
    _drive(world, [-0.5, 5.0], 30)          # straight north, through the outer wall
    assert world.state == "blocked"
    y = world.pos[1]
    world.tick(1.0)
    assert world.pos[1] == y                # it stays put once blocked


def test_message_shape(world):
    world.tick(0.1)
    data = json.loads(json.dumps(world.sensors_message(camera=False)))
    assert set(data["pose"]) == {"pos", "yaw"} and len(data["pose"]["pos"]) == 3
    assert len(data["lidar"]) == 360
    assert all(0 < r <= sensors.MAX_RANGE for r in data["lidar"])
    assert np.array(data["thermal"]).shape == (12, 16)
    assert set(data["acoustic"]) == {"bearing", "level"}
    assert -180 < data["acoustic"]["bearing"] <= 180 and 0 <= data["acoustic"]["level"] <= 1
    assert "camera" not in data


def test_lidar_sees_the_wall_ahead(world):
    _drive(world, [-0.5, -0.3], 10)
    ranges = sensors.lidar(world.m, world.d, world.pos, world.scout)
    assert ranges.min() < sensors.MAX_RANGE
    assert ranges.min() > 0


def test_thermal_and_sound_find_the_casualty(world):
    far = world.sensors_message(camera=False)              # outside the building, walls between
    assert np.max(far["thermal"]) == pytest.approx(0.1)
    for target in ([-0.5, -0.3], [-0.3, 0.25], [-0.2, 0.25]):   # in the doorway facing room 2
        _drive(world, target, 15)
    near = world.sensors_message(camera=False)
    assert np.max(near["thermal"]) > 0.5
    assert near["acoustic"]["level"] > far["acoustic"]["level"]


def test_start_streams_at_10hz_and_follows_goto():
    class FakeBus:
        def __init__(self):
            self.sent, self.subs = [], {}

        async def publish(self, topic, data):
            self.sent.append((time.monotonic(), topic, data))

        def subscribe(self, topic, callback):
            self.subs.setdefault(topic, []).append(callback)

    async def main():
        bus = FakeBus()
        world = await sim.start(bus)
        for cb in bus.subs["scout/goto"]:
            cb({"target": [-0.5, -0.3, 0.075], "reason": "test"})
        await asyncio.sleep(2.05)
        world.task.cancel()
        return bus

    bus = asyncio.run(main())
    stream = [(t, d) for t, topic, d in bus.sent if topic == "sensors/scout"]
    assert 15 <= len(stream) <= 22
    rate = (len(stream) - 1) / (stream[-1][0] - stream[0][0])
    assert 8 <= rate <= 12, f"{rate:.1f} Hz"
    assert stream[-1][1]["pose"]["pos"][1] > stream[0][1]["pose"]["pos"][1] + 0.3


def test_record_writes_the_fake(tmp_path):
    from sim import record

    out, _ = record.record(seconds=5, out=tmp_path / "s.jsonl")
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(lines) == 50
    assert {line["topic"] for line in lines} == {"sensors/scout"}
    assert all("camera" not in line["data"] for line in lines)
