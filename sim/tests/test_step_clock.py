"""SIM_CLOCK=step: the sim loop ticks a fixed dt without waiting on the wall clock (SIM-STEP-CLOCK)."""

import asyncio
import time

import pytest

import sim


class Done(Exception):
    pass


class FakeResponder:
    def step(self, dt):
        pass

    def pose_message(self, t):
        return {"t": t}


class FakeWorld:
    """Just enough of sim.world.World for run(): counts ticks and stops after `ticks`."""

    def __init__(self, ticks):
        self.t, self.ticks, self.dts = 0.0, ticks, []
        self.responder = FakeResponder()

    def tick(self, dt):
        if len(self.dts) == self.ticks:
            raise Done
        self.dts.append(dt)
        self.t += dt
        return []

    def sensors_message(self):
        return {"t": self.t}


class FakeBus:
    def __init__(self):
        self.seen = []

    async def publish(self, topic, data):
        self.seen.append((topic, data["t"]))


def _run(world, bus):
    with pytest.raises(Done):
        asyncio.run(sim.run(world, bus, rate_hz=10))


def test_step_clock_ticks_fixed_dt_without_waiting(monkeypatch):
    monkeypatch.setenv("SIM_CLOCK", "step")
    world, bus = FakeWorld(ticks=50), FakeBus()   # 5 s of sim time
    started = time.monotonic()
    _run(world, bus)
    assert time.monotonic() - started < 1.0      # no wall-clock pacing
    assert world.dts == [0.1] * 50
    assert world.t == pytest.approx(5.0)


def test_step_clock_publishes_the_same_stream_every_run(monkeypatch):
    monkeypatch.setenv("SIM_CLOCK", "step")
    streams = []
    for _ in range(3):
        world, bus = FakeWorld(ticks=30), FakeBus()
        _run(world, bus)
        streams.append(bus.seen)
    assert streams[0] == streams[1] == streams[2]
    assert len(streams[0]) == 60   # responder/pose + sensors/scout per tick


@pytest.mark.parametrize("clock_name", ["wall", "step"])
def test_both_clocks_run_a_scout_only_world(monkeypatch, clock_name):
    monkeypatch.setenv("SIM_CLOCK", clock_name)
    world, bus = FakeWorld(ticks=3), FakeBus()
    world.responder = None

    _run(world, bus)

    assert world.t == pytest.approx(0.3)
    assert bus.seen == [("sensors/scout", pytest.approx(t)) for t in (0.1, 0.2, 0.3)]


def test_default_clock_still_paces_to_real_time(monkeypatch):
    monkeypatch.delenv("SIM_CLOCK", raising=False)
    assert sim.clock() == "wall"
    world, bus = FakeWorld(ticks=3), FakeBus()
    started = time.monotonic()
    _run(world, bus)
    assert time.monotonic() - started >= 0.25    # 3 ticks of 0.1 s, paced


def test_unknown_clock_is_refused(monkeypatch):
    monkeypatch.setenv("SIM_CLOCK", "turbo")
    with pytest.raises(ValueError, match="SIM_CLOCK"):
        sim.clock()
