"""RADIO-HANDOFF-TEST: L3 relay loss hands the planner offline, then forwards queued data.

Seam: real radio model/scene walls -> RelayTransport -> HubLink -> validated Bus,
plus status/link -> planner Loop. This is not delivery of a radio supply item.
Antenna positions are sampled explicitly; no physical Scout descent is claimed.
"""

import asyncio
import itertools

import sim
from coord.hub import Bus
from coord.messages import validate_payload
from hw.bridge import HubLink, LoopbackTransport, RobotSource
from hw.relay import Relay, RelayTransport
from planner.loop import Loop
from planner.route import RoutePlanner
from sim.world import World


def test_radio_relay_loss_hands_off_offline_and_recovery_forwards_real_frames():
    async def run():
        world = World(render=False, seed=0)
        bus = Bus()
        planner = Loop(bus, RoutePlanner(bus)).attach()
        radio = Relay(base=world.pos, walls=sim._walls(world), seed=0)
        transport = RelayTransport(LoopbackTransport(), radio)
        hub = HubLink(transport, bus, validate=validate_payload)
        source = RobotSource(transport)
        received, expected, links = [], [], []
        bus.subscribe("sensors/scout", received.append)
        bus.subscribe("status/link", lambda data: links.append(data["online"]))

        async def status(events):
            for topic, data in events:
                await bus.publish(topic, data)

        async def send_frame():
            frame = world.sensors_message(camera=False)
            expected.append(validate_payload("sensors/scout", frame))
            source.send("sensors/scout", frame)
            await asyncio.sleep(0)  # HubLink schedules delivery onto this event loop.

        try:
            await status(radio.step(0, world.pos))
            await send_frame()
            assert len(received) == 1
            assert planner.online is True

            # Same backup-scene antenna survey as L3: attenuation comes from real
            # MuJoCo wall intersections, not a mocked delivery probability or route.
            survey = [(-0.5, -1.5), (-0.5, -0.6), (-0.9, 0.25), (-0.2, 0.25),
                      (0.6, 0.6), (1.25, 0.6), (1.8, 0.9)]
            t = 0.0
            for a, b in itertools.pairwise(survey):
                for i in range(10):
                    f = i / 9
                    t += 0.1
                    await status(radio.step(t, (a[0] + (b[0] - a[0]) * f,
                                                a[1] + (b[1] - a[1]) * f, 0.075)))
            assert radio.path == ["scout", "relay1", "base"]
            world.tick(0.1)
            await send_frame()
            assert len(received) == 2  # forwarded through the breadcrumb, not just direct

            await status(radio.fail("relay1", t))
            assert radio.path == []
            assert planner.online is False
            assert links == [True, False]
            assert any(msg["topic"] == "log/decision" and msg["data"]["outcome"] == "offline"
                       for msg in bus.history)
            for _ in range(2):
                world.tick(0.1)
                await send_frame()
            transport.flush()
            await asyncio.sleep(0)
            assert len(received) == 2  # no bypass around the disconnected radio
            assert radio.status()["buffered"] == 2

            await status(radio.step(t + 1, world.pos))  # near the base: a direct link returns
            assert radio.path == ["scout", "base"]
            assert "relay1" not in radio.nodes
            assert planner.online is True
            assert links == [True, False, True]
            transport.flush()
            await asyncio.sleep(0)
            world.tick(0.1)
            await send_frame()
            assert received == expected  # old buffered frames, then live; no loss/duplicates
            assert len(received) == 5
            assert radio.status()["buffered"] == 0
            assert hub.received == 5 and hub.rejected == 0
        finally:
            transport.close()

    asyncio.run(run())
