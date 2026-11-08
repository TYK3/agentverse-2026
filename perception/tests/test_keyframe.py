"""PERCEPTION-KEYFRAME: the grid's LiDAR scan and the hazards depth cloud skip sensors/scout frames
from a Scout that has not moved 5 cm or turned 5 degrees, but still run at least every STILL_EVERY-th
frame (so cells in view keep earning the passes the scan diff needs), on every frame for a while
after a world/change or a scout/goto, and perception's clock (grid.t) advances on every frame.
Casualties, the listener and hazard motion are not keyframed."""

import asyncio
import itertools
import math

import pytest

pytest.importorskip("pydantic")

import perception
from perception import Keyframe


def frame(t, x=0.0, y=0.0, yaw=0.0):
    return {"t": t, "pose": {"pos": [x, y, 0.075], "yaw": yaw}}


def test_first_frame_is_a_keyframe():
    assert Keyframe().due(frame(0.1))


def test_a_still_scout_is_processed_once_then_every_still_every_th_frame():
    k = Keyframe()
    due = [k.due(frame(0.1 * i)) for i in range(1, 22)]
    assert due[0] is True
    assert sum(due) == 1 + 20 // perception.STILL_EVERY
    gaps = [i for i, d in enumerate(due) if d]
    assert all(b - a == perception.STILL_EVERY for a, b in itertools.pairwise(gaps))


def test_a_moving_scout_is_processed_every_frame():
    k = Keyframe()
    assert all(k.due(frame(0.1 * i, x=0.06 * i)) for i in range(1, 20))


def test_a_turning_scout_is_processed_every_frame():
    k = Keyframe()
    assert all(k.due(frame(0.1 * i, yaw=math.radians(6) * i)) for i in range(1, 20))


def test_small_moves_add_up_to_a_keyframe():
    # 1 cm a frame: below the threshold each frame, but measured from the last keyframe.
    k = Keyframe()
    due = [k.due(frame(0.1 * i, x=0.01 * i)) for i in range(12)]
    assert due[0] and due[5], due


def test_yaw_wraps_round_pi():
    k = Keyframe()
    assert k.due(frame(0.1, yaw=math.pi - 0.01))
    assert not k.due(frame(0.2, yaw=-math.pi + 0.01))      # 1.1 degrees apart, not 359


def test_forced_window_processes_every_frame_then_ends():
    k = Keyframe()
    k.due(frame(0.0))
    k.force(0.0, 1.0)
    assert all(k.due(frame(0.1 * i)) for i in range(1, 11))     # t 0.1 .. 1.0
    assert not k.due(frame(1.1))


class Bus:
    def __init__(self):
        self.subs = {}

    def subscribe(self, topic, fn):
        self.subs.setdefault(topic, []).append(fn)

    async def publish(self, topic, data):
        for fn in self.subs.get(topic, []):
            r = fn(data)
            if asyncio.iscoroutine(r):
                await r


def scan(t, x=0.5, y=0.5, yaw=0.0):
    return {"t": t, "pose": {"pos": [x, y, 0.075], "yaw": yaw}, "lidar": [1.0] * 72,
            "thermal": [[0.0]], "acoustic": {"bearing": 0.0, "level": 0.0},
            "motion": {"state": "idle", "target": None}}


def test_wired_in_start_grid_scans_fewer_frames_but_its_clock_runs_every_frame(monkeypatch):
    calls = []

    async def go():
        bus = Bus()
        grid = await perception.start(bus)
        real = grid.add_scan
        monkeypatch.setattr(grid, "add_scan", lambda *a, **kw: (calls.append(1), real(*a, **kw)))
        for i in range(1, 21):
            await bus.publish("sensors/scout", scan(0.1 * i))
        t_still = grid.t
        await bus.publish("world/change", {"kind": "aftershock", "t": t_still})
        before = len(calls)
        for i in range(21, 26):
            await bus.publish("sensors/scout", scan(0.1 * i))
        for task in list(perception._tasks):
            task.cancel()
        return t_still, len(calls) - before

    t_still, after_change = run(go())
    assert t_still == pytest.approx(2.0), "grid.t (perception's clock) advances on skipped frames too"
    assert len(calls) - after_change == 1 + 19 // perception.STILL_EVERY, "a still Scout is not rescanned every frame"
    assert after_change == 5, "every frame is scanned after a world/change"


def run(coro):
    return asyncio.run(coro)
