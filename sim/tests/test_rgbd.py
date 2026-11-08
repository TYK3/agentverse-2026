"""Y9 checks: the Scout's depth camera gives measured scene-frame points that match the geometry, stay
within the contract's 2048 cap and the camera's range, hide the robots, and repeat for a fixed seed."""

import math

import numpy as np
import pytest

from sim import rgbd
from sim.world import World

WALL_X = -0.05          # face of interior wall b6 seen from room 1 (sim/scenes/backup.xml)


@pytest.fixture
def world():
    w = World(render=False)
    w._set_pose((-0.5, -0.6), 0.0)          # Scout in room 1, camera facing +x at wall b6, 0.35 m away
    w.tick(0.1)
    return w


def camera(world, **kw):
    cam = rgbd.RGBD(world.m, **kw)
    if not cam.available:
        pytest.skip("no GL context for depth frames")
    return cam


def test_points_land_on_the_wall_and_floor(world):
    f = camera(world, noise=0).frame(world.d)
    pts = np.array(f["points"])
    above = pts[pts[:, 2] > 0.005]
    assert len(above) > 100
    assert np.abs(above[:, 0] - WALL_X).max() < 0.01, "every point above the floor is on the wall face"
    before = pts[pts[:, 0] < WALL_X - 0.01]
    assert len(before) > 50 and np.abs(before[:, 2]).max() < 0.005, "everything in front of the wall is floor"
    assert f["points_from"] == pytest.approx(list(world.d.cam_xpos[world.m.camera("scout_cam").id]), abs=1e-3)


def test_at_most_2048_points_even_from_a_bigger_render(world):
    big = camera(world, width=320, height=240, noise=0)
    assert len(big.frame(world.d)["points"]) <= rgbd.MAX_POINTS
    assert len(camera(world).frame(world.d)["points"]) <= rgbd.MAX_POINTS


def test_points_stay_within_the_depth_range(world):
    world._set_pose((-0.5, -1.5), math.pi / 2)    # looking into the building through the breach
    world.tick(0.1)
    f = camera(world, noise=0).frame(world.d)
    origin = np.array(f["points_from"])
    rot = world.d.cam_xmat[world.m.camera("scout_cam").id].reshape(3, 3)
    depth = -(np.array(f["points"]) - origin) @ rot[:, 2]          # distance along the optical axis
    assert depth.min() >= rgbd.MIN_RANGE - 1e-6 and depth.max() <= rgbd.MAX_RANGE + 1e-6


def test_robots_are_not_in_the_cloud(world):
    # Scout just in front of the Responder (-0.5, -1.77), looking straight at it.
    world._set_pose((-0.5, -1.3), -math.pi / 2)
    world.tick(0.1)
    pts = np.array(camera(world, noise=0).frame(world.d)["points"])
    rx, ry = -0.5, -1.77
    # chassis height only: the supplies riding on its deck (z > 0.1) are ordinary objects and stay visible
    inside = (np.abs(pts[:, 0] - rx) < 0.07) & (np.abs(pts[:, 1] - ry) < 0.16) & (pts[:, 2] > 0.01) & (pts[:, 2] < 0.095)
    assert not inside.any(), "the Responder's body (group 3) is hidden from the depth camera"


def test_noise_is_small_and_repeatable(world):
    clean = np.array(camera(world, noise=0).frame(world.d)["points"])
    a = np.array(camera(world, seed=7).frame(world.d)["points"])
    b = np.array(camera(world, seed=7).frame(world.d)["points"])
    assert np.array_equal(a, b), "same seed, same frame"
    err = np.linalg.norm(a - clean, axis=1)
    assert 0 < err.mean() < 0.005, "millimetres of noise at 0.35 m"


def test_sensors_scout_with_points_matches_the_contract(world):
    messages = pytest.importorskip("coord.messages")
    data = world.sensors_message(camera=False)
    data.update(camera(world).frame(world.d))
    messages.validate_payload("sensors/scout", data)


def test_no_gl_context_means_no_points(world, monkeypatch):
    from sim import sensors

    monkeypatch.setattr(sensors, "make_renderer", lambda *a, **k: None)
    cam = rgbd.RGBD(world.m)
    assert not cam.available and cam.frame(world.d) is None


def test_sim_loop_adds_points_to_sensors_scout_at_2_hz():
    import asyncio

    import sim

    class Bus:
        def __init__(self):
            self.frames = []

        def subscribe(self, topic, fn):
            pass

        async def publish(self, topic, data):
            if topic == "sensors/scout":
                self.frames.append(data)

    async def go():
        bus = Bus()
        world = await sim.start(bus)
        if world.rgbd is None or not world.rgbd.available:
            world.task.cancel()
            return None
        await asyncio.sleep(1.3)
        world.task.cancel()
        await asyncio.gather(world.task, return_exceptions=True)
        return bus.frames

    frames = asyncio.run(go())
    if frames is None:
        pytest.skip("no GL context for depth frames")
    with_points = [f for f in frames if "points" in f]
    assert with_points and len(with_points) < len(frames), "points on some frames, not all (2 Hz of 10 Hz)"
    assert all(len(f["points"]) <= rgbd.MAX_POINTS and len(f["points_from"]) == 3 for f in with_points)
