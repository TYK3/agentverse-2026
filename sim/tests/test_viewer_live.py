"""SIM_VIEWER checks: off unless asked, a faked window tracks the pose, launch failure does not crash."""

import asyncio
import logging
import sys
import threading
import time

import mujoco
import numpy as np
import pytest

from sim import viewer_live

XML = """
<mujoco>
  <worldbody>
    <body name="box" pos="0 0 0.5">
      <freejoint/>
      <geom type="box" size="0.1 0.1 0.1"/>
    </body>
    <body name="scout" mocap="true" pos="1 0 0.2">
      <geom type="sphere" size="0.05"/>
    </body>
  </worldbody>
</mujoco>
"""


class Boom:
    """Any attribute access is a failure: the off path must not read the world."""

    def __getattr__(self, name):
        raise AssertionError(name)


class World:
    def __init__(self):
        self.m = mujoco.MjModel.from_xml_string(XML)
        self.d = mujoco.MjData(self.m)
        mujoco.mj_forward(self.m, self.d)
        self.published = []

    def publish(self, *args):
        self.published.append(args)

    def tick(self, dt=0.1):
        return [("sensors/scout", {"t": dt})]


class FakeViewer:
    """Stand-in for ``mujoco.viewer.launch_passive``'s handle."""

    def __init__(self, on_sync=None):
        self.on_sync = on_sync
        self.syncs = 0
        self.closed = False
        self.running = True
        self.done = threading.Event()
        self._cv = threading.Condition()

    def is_running(self):
        return self.running

    def sync(self):
        with self._cv:
            self.syncs += 1
            self._cv.notify_all()
        if self.on_sync is not None:
            self.on_sync(self)

    def close(self):
        self.running = False
        self.closed = True
        self.done.set()

    def wait_syncs(self, n, timeout=2.0):
        deadline = time.monotonic() + timeout
        with self._cv:
            while self.syncs < n:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cv.wait(remaining)
            return True


def _viewer_threads():
    return [thread for thread in threading.enumerate() if thread.name == "sim-viewer"]


def _arm(monkeypatch, launch):
    monkeypatch.setenv("SIM_VIEWER", "1")
    monkeypatch.setattr(viewer_live, "display_available", lambda: True)
    monkeypatch.setattr(viewer_live, "launch_passive", launch)


def test_off_by_default_does_not_touch_the_world(monkeypatch, caplog):
    monkeypatch.delenv("SIM_VIEWER", raising=False)
    sys.modules.pop("mujoco.viewer", None)
    caplog.set_level(logging.WARNING, logger="sim.viewer")
    before = threading.active_count()

    assert viewer_live.enabled() is False
    assert viewer_live.attach(Boom()) is None
    viewer_live.sync(None)
    viewer_live.close(None)

    assert threading.active_count() == before
    assert _viewer_threads() == []
    assert "mujoco.viewer" not in sys.modules
    assert caplog.records == []

    world = World()
    assert viewer_live.attach(world) is None
    assert not hasattr(world, "viewer")
    assert world.tick(0.2) == [("sensors/scout", {"t": 0.2})]
    assert world.published == []


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "2"])
def test_only_the_string_1_enables_the_viewer(monkeypatch, value):
    monkeypatch.setenv("SIM_VIEWER", value)
    assert viewer_live.enabled() is False
    assert viewer_live.attach(Boom()) is None


def test_display_available_follows_the_session(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert viewer_live.display_available() is False
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert viewer_live.display_available() is True
    monkeypatch.delenv("WAYLAND_DISPLAY")
    monkeypatch.setenv("DISPLAY", ":1")
    assert viewer_live.display_available() is True
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("DISPLAY")
    assert viewer_live.display_available() is True


def test_no_display_warns_and_does_not_launch(monkeypatch, caplog):
    monkeypatch.setenv("SIM_VIEWER", "1")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    sys.modules.pop("mujoco.viewer", None)
    launched = []
    monkeypatch.setattr(
        viewer_live, "launch_passive", lambda *args, **kwargs: launched.append(1)
    )
    caplog.set_level(logging.WARNING, logger="sim.viewer")

    assert viewer_live.attach(Boom()) is None

    assert launched == []
    assert "mujoco.viewer" not in sys.modules
    assert _viewer_threads() == []
    assert "no display is available" in caplog.text


def test_enabled_viewer_tracks_the_pose_and_does_not_step(monkeypatch):
    world = World()
    scout = int(world.m.body("scout").id)
    live_scout = world.d.xpos[scout].copy()
    live_qpos = world.d.qpos.copy()
    steps, forwards, kinematics = [], [], []

    real_step, real_forward, real_kinematics = mujoco.mj_step, mujoco.mj_forward, mujoco.mj_kinematics

    def spy_step(model, data):
        steps.append(data)
        return real_step(model, data)

    def spy_forward(model, data):
        forwards.append(data)
        return real_forward(model, data)

    def spy_kinematics(model, data):
        kinematics.append(data)
        return real_kinematics(model, data)

    monkeypatch.setattr(mujoco, "mj_step", spy_step)
    monkeypatch.setattr(mujoco, "mj_forward", spy_forward)
    monkeypatch.setattr(mujoco, "mj_kinematics", spy_kinematics)

    seen = {}
    fake = FakeViewer()

    def launch(model, data):
        seen["model"] = model
        seen["data"] = data
        return fake

    _arm(monkeypatch, launch)

    def tick(dt=0.1):
        world.d.qpos[0] = 0.4
        world.d.time = 1.25
        world.d.mocap_pos[0] = [4.0, 5.0, 0.2]
        return [("sensors/scout", {"t": dt})]

    world.tick = tick
    viewer = viewer_live.attach(world)
    try:
        assert viewer is not None and world.viewer is viewer
        assert viewer.wait(2.0)
        assert fake.wait_syncs(1)
        assert world.tick(0.1) == [("sensors/scout", {"t": 0.1})]
        before = fake.syncs
        assert world.tick(0.1) == [("sensors/scout", {"t": 0.1})]
        assert fake.wait_syncs(before + 1)

        view = seen["data"]
        assert seen["model"] is world.m
        assert view is not world.d
        assert not np.shares_memory(view.qpos, world.d.qpos)
        assert view.qpos[0] == pytest.approx(0.4)
        assert view.time == pytest.approx(1.25)
        assert view.xpos[scout] == pytest.approx([4.0, 5.0, 0.2])
        assert world.d.time == pytest.approx(1.25)
        assert world.d.qpos[0] == pytest.approx(0.4)
        assert np.allclose(world.d.xpos[scout], live_scout)
        assert np.allclose(world.d.qpos[1:], live_qpos[1:])
        assert steps == [] and forwards == []
        assert kinematics and all(data is view for data in kinematics)
        assert world.published == []
    finally:
        viewer_live.close(viewer)
    assert fake.closed
    assert _viewer_threads() == []


def test_attach_and_tick_do_not_block_the_asyncio_loop(monkeypatch):
    world = World()
    entered = threading.Event()
    release = threading.Event()

    def block(fake):
        entered.set()
        release.wait(2.0)

    fake = FakeViewer(on_sync=block)

    def launch(model, data):
        entered_launch.set()
        if not release_launch.wait(2.0):
            raise RuntimeError("viewer launch did not return")
        return fake

    entered_launch = threading.Event()
    release_launch = threading.Event()
    _arm(monkeypatch, launch)

    started = time.monotonic()
    viewer = viewer_live.attach(world)
    try:
        assert time.monotonic() - started < 0.1
        assert entered_launch.wait(2.0)
        release_launch.set()
        assert viewer.wait(2.0)
        assert entered.wait(2.0)

        async def main():
            task = asyncio.create_task(asyncio.sleep(0.05))
            t0 = time.monotonic()
            viewer_live.sync(viewer)
            elapsed = time.monotonic() - t0
            assert world.tick(0.1) == [("sensors/scout", {"t": 0.1})]
            await task
            return elapsed

        assert asyncio.run(main()) < 0.1
    finally:
        release_launch.set()
        release.set()
        viewer_live.close(viewer)
    assert fake.closed
    assert _viewer_threads() == []


def test_launch_failure_warns_and_the_loop_continues(monkeypatch, caplog):
    world = World()
    qpos = world.d.qpos.copy()
    calls = []

    def launch(model, data):
        calls.append(data)
        raise RuntimeError("glfw has no display")

    _arm(monkeypatch, launch)
    caplog.set_level(logging.WARNING, logger="sim.viewer")
    viewer = viewer_live.attach(world)
    try:
        assert viewer is not None
        assert viewer.wait(2.0) is False
        assert world.tick(0.1) == [("sensors/scout", {"t": 0.1})]
        viewer_live.sync(viewer)
        assert np.array_equal(world.d.qpos, qpos)
        assert world.d.time == pytest.approx(0.0)
        assert calls and calls[0] is not world.d
        assert "could not start" in caplog.text
        assert "RuntimeError" in caplog.text
        assert "glfw has no display" in caplog.text
        assert world.published == []
    finally:
        viewer_live.close(viewer)
        viewer_live.close(viewer)
    assert _viewer_threads() == []


def test_closing_the_window_stops_the_viewer(monkeypatch):
    world = World()

    def shut(fake):
        fake.running = False

    fake = FakeViewer(on_sync=shut)
    _arm(monkeypatch, lambda model, data: fake)
    viewer = viewer_live.attach(world)
    try:
        assert fake.done.wait(2.0)
        assert viewer.wait(2.0) is False
        assert fake.closed
        qpos = world.d.qpos.copy()
        assert world.tick(0.1) == [("sensors/scout", {"t": 0.1})]
        assert np.array_equal(world.d.qpos, qpos)
    finally:
        viewer_live.close(viewer)
    assert _viewer_threads() == []


def test_shutdown_hook_is_registered_and_removed(monkeypatch):
    world = World()
    fake = FakeViewer()
    registered = []
    real_register = viewer_live.atexit.register

    def spy(func, *args, **kwargs):
        registered.append(func)
        return real_register(func, *args, **kwargs)

    monkeypatch.setattr(viewer_live.atexit, "register", spy)
    _arm(monkeypatch, lambda model, data: fake)
    viewer = viewer_live.attach(world)
    try:
        assert viewer.wait(2.0)
        assert viewer.close in registered
    finally:
        viewer_live.close(viewer)
    assert _viewer_threads() == []
