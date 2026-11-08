"""Y10 part 2: sim sensors through chip driver stubs and one bridge, same path as a real robot."""

import asyncio
import json
import math

import numpy as np
import pytest

import hw
from hw import bridge, drivers


def ideal(t, yaw=0.0, lidar=None):
    return {"t": t, "pose": {"pos": [0.5, -1.0, 0.075], "yaw": yaw},
            "lidar": lidar if lidar is not None else [1.0] * 360,
            "thermal": [[0.1] * 16 for _ in range(12)], "acoustic": {"bearing": 179.0, "level": 0.5},
            "motion": {"state": "idle", "target": None}}


def test_thermal_runs_at_lepton_rate_and_arrives_late():
    d = drivers.ThermalDriver(np.random.default_rng(1))
    taken = sum(d.offer(round(k * 0.01, 2), [[0.5]]) for k in range(200))  # 2 s offered at 100 Hz
    assert taken in (17, 18)  # 8.7 Hz
    d2 = drivers.ThermalDriver()
    d2.offer(0.0, [[0.5]])
    assert not d2.poll(0.1) and d2.latest is None  # 115 ms latency
    assert d2.poll(0.12) and d2.latest_t == pytest.approx(0.115)


def test_lidar_noise_keeps_misses_and_drops_too_close_returns():
    d = drivers.LidarDriver(np.random.default_rng(2))
    ranges = [2.0] * 300 + [6.0] * 50 + [0.01] * 10
    out = np.array(d.measure(ranges))
    hits = out[:300]
    assert abs(hits.mean() - 2.0) < 0.01 and 0.01 < hits.std() < 0.03  # 1% of range
    assert (out[300:] == 6.0).all()  # misses and too-close returns read as a miss


def test_acoustic_bearing_wraps_and_silence_has_no_bearing_noise():
    d = drivers.AcousticDriver(np.random.default_rng(3))
    vals = [d.measure({"bearing": 179.0, "level": 0.5})["bearing"] for _ in range(200)]
    assert all(-180 <= v < 180 for v in vals) and any(v < 0 for v in vals)
    assert d.measure({"bearing": 30.0, "level": 0.0}) == {"bearing": 30.0, "level": 0.0}


def test_imu_heading_noise_is_small_and_wrapped():
    d = drivers.ImuDriver(np.random.default_rng(4))
    vals = np.array([d.measure(math.pi - 0.001) for _ in range(500)])
    assert (np.abs(vals) <= math.pi + 1e-3).all()  # wrapped, then rounded to 3 places
    err = np.angle(np.exp(1j * (vals - (math.pi - 0.001))))
    assert np.degrees(np.std(err)) == pytest.approx(0.5, abs=0.1)


def test_frames_wait_for_every_channel_then_keep_the_contract_shape():
    h = drivers.ScoutHardware(seed=0)
    frames = [h.step(ideal(round(k * 0.1, 1))) for k in range(10)]
    assert frames[0] is None  # nothing has cleared its latency yet
    frame = next(f for f in frames if f is not None)
    assert set(frame) == {"t", "pose", "lidar", "thermal", "acoustic", "motion"}
    assert len(frame["lidar"]) == 360 and len(frame["thermal"]) == 12
    messages = pytest.importorskip("coord.messages")
    messages.validate_payload("sensors/scout", frame)


def test_every_figure_says_where_it_comes_from():
    for row in drivers.ScoutHardware().table():
        assert row["notes"]["rate_hz"].startswith(("source:", "assumed:"))
        assert row["rate_hz"] > 0 and row["latency_s"] >= 0


def test_mqtt_wildcards():
    assert bridge._match("aftershock/#", "aftershock/sensors/scout")
    assert bridge._match("aftershock/+/scout", "aftershock/sensors/scout")
    assert not bridge._match("aftershock/+", "aftershock/sensors/scout")
    assert not bridge._match("other/#", "aftershock/sensors/scout")


class Bus:
    def __init__(self):
        self.got = []

    async def publish(self, topic, data):
        self.got.append((topic, data))


def test_sim_and_a_real_robot_reach_the_hub_the_same_way():
    async def run():
        bus = Bus()
        t = bridge.LoopbackTransport()
        robot = hw.attach(bus, transport=t)
        for k in range(10):
            robot.feed(ideal(round(k * 0.1, 1)))
        real = bridge.RobotSource(t, "limo-1")  # outside software: talks to the bridge only
        real.send("sensors/scout", ideal(1.5))
        await asyncio.sleep(0)
        return bus, robot

    bus, robot = asyncio.run(run())
    assert robot.sent > 0 and len(bus.got) == robot.sent + 1
    assert {topic for topic, _ in bus.got} == {"sensors/scout"}
    assert bus.got[-1][1]["t"] == 1.5


def test_bridge_rejects_bad_envelopes_and_non_robot_topics():
    async def run():
        bus = Bus()
        t = bridge.LoopbackTransport()
        link = bridge.HubLink(t, bus)
        t.publish("aftershock/sensors/scout", b"not json")
        t.publish("aftershock/gate/answer", json.dumps({"topic": "gate/answer", "data": {}}).encode())
        t.publish("aftershock/sensors/scout", json.dumps({"topic": "gate/answer", "data": {}}).encode())
        with pytest.raises(ValueError):
            bridge.RobotSource(t).send("gate/answer", {"id": "g1", "approved": True, "by": "robot"})
        await asyncio.sleep(0)
        return bus, link

    bus, link = asyncio.run(run())
    assert bus.got == [] and link.rejected == 3


def test_from_env():
    assert isinstance(bridge.from_env("loopback"), bridge.LoopbackTransport)
    with pytest.raises(ValueError):
        bridge.from_env("http://example")


def test_sim_lane_uses_the_bridge_when_hw_is_on(monkeypatch):
    import sim

    monkeypatch.setenv("AFTERSHOCK_HW", "1")
    monkeypatch.setenv("AFTERSHOCK_BRIDGE", "loopback")

    class HubBus(Bus):
        def subscribe(self, topic, fn):
            pass

    async def go():
        bus = HubBus()
        world = await sim.start(bus, loop=False)
        assert world.hw is not None
        task = asyncio.create_task(sim.run(world, bus))
        await asyncio.sleep(1.5)
        task.cancel()
        return bus, world

    bus, world = asyncio.run(go())
    scout = [d for topic, d in bus.got if topic == "sensors/scout"]
    assert scout and world.hw.link.received == len(scout)
