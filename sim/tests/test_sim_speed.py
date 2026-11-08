"""SIM-SPEED: batched LiDAR gives the same ranges as the per-ray loop; the RGB frame is rendered at 2 Hz."""

import asyncio

import mujoco
import numpy as np
import pytest

import sim
from sim import scene, sensors
from sim.world import World


def _loop_lidar(m, d, origin, exclude, n=360, max_range=sensors.MAX_RANGE):
    """The pre-SIM-SPEED lidar(): one mj_ray per direction."""
    ranges = np.full(n, max_range)
    for k in range(n):
        a = 2 * np.pi * k / n
        dist, _ = sensors._ray(m, d, origin, [np.cos(a), np.sin(a), 0.0], exclude, sensors.SENSE_GROUPS)
        if dist >= 0:
            ranges[k] = min(dist, max_range)
    return ranges


@pytest.mark.parametrize("path", [scene.BACKUP, scene.BUILDING])
def test_batched_lidar_matches_per_ray_loop(path):
    w = World(path=path, render=False)
    base = np.array(w.sensor_origin, float)
    for dx, dy in [(0, 0), (0.3, -0.2), (-0.5, 0.4)]:
        origin = base + [dx, dy, 0.0]
        got = sensors.lidar(w.m, w.d, origin, w.scout)
        assert got.shape == (360,)
        np.testing.assert_allclose(got, _loop_lidar(w.m, w.d, origin, w.scout), atol=1e-9)


def test_lidar_falls_back_without_multiray(monkeypatch):
    w = World(path=scene.BACKUP, render=False)
    origin = np.array(w.sensor_origin, float)
    want = sensors.lidar(w.m, w.d, origin, w.scout)
    monkeypatch.delattr(mujoco, "mj_multiRay")
    np.testing.assert_allclose(sensors.lidar(w.m, w.d, origin, w.scout), want, atol=1e-9)


class Done(Exception):
    pass


class FakeResponder:
    def step(self, dt):
        pass

    def pose_message(self, t):
        return {"t": t}


class CameraWorld:
    """Just enough of World for run(): records which ticks asked for a camera frame."""

    def __init__(self, ticks):
        self.t, self.ticks, self.asked = 0.0, ticks, []
        self.responder = FakeResponder()

    def tick(self, dt):
        if len(self.asked) == self.ticks:
            raise Done
        self.t = round(self.t + dt, 6)
        return []

    def sensors_message(self, camera=True):
        self.asked.append(camera)
        return {"t": self.t}


class FakeBus:
    async def publish(self, topic, data):
        pass


def test_camera_frame_rendered_at_2hz_off_the_depth_tick(monkeypatch):
    monkeypatch.setenv("SIM_CLOCK", "step")
    world = CameraWorld(ticks=50)                    # 5 s at 10 Hz
    with pytest.raises(Done):
        asyncio.run(sim.run(world, FakeBus(), rate_hz=10))
    ticks = [k + 1 for k, cam in enumerate(world.asked) if cam]   # world.t / dt after each tick
    assert len(ticks) == 10                          # 2 Hz, not 10 Hz
    assert all(k % sim.RGBD_EVERY != 0 for k in ticks)   # never on the depth-frame tick
