"""sim lane: the MuJoCo world. The hub (coord/hub.py) calls `start(bus)` on startup."""

import asyncio
import logging
import os
import time

from sim import debris, inject, responder, scene
from sim.world import World

RATE_HZ = 10
log = logging.getLogger("sim")


async def run(world, bus, rate_hz=RATE_HZ):
    """Tick the world in real time; publish its events and sensors/scout at rate_hz."""
    dt = 1.0 / rate_hz
    while True:
        started = time.monotonic()
        world.responder.step(dt)      # the Responder (T06) moves on the same tick as the physics
        events = world.tick(dt)
        sensors = world.sensors_message()
        hw_robot = getattr(world, "hw", None)
        if hw_robot is not None:  # Y10: through the chip driver stubs and the bridge
            hw_robot.feed(sensors)
        else:
            events.append(("sensors/scout", sensors))
        for topic, data in events:
            try:
                await bus.publish(topic, data)
            except Exception:  # a rejected message must not stop the world
                log.exception("publish %s failed", topic)
        await asyncio.sleep(max(0.0, dt - (time.monotonic() - started)))


async def start(bus, loop=True):
    """Load the backup scene and wire the sim lane to the bus.

    Publishes scene/loaded; follows scout/goto; answers route/proposed with route/verified from a
    cached physics check; streams sensors/scout at 10 Hz and world/change after an aftershock or an
    injected block. On the hub it also serves POST /inject (sim/inject.py). The Responder (T06,
    sim/responder.py, `world.responder`) follows route/proposed, gate/* and responder/action, freezes
    on world/change and reports every outcome as log/decision.
    """
    world = World()
    await bus.publish("scene/loaded", scene.scene_loaded(world.m, world.d))
    bus.subscribe("scout/goto", world.goto)
    bus.subscribe("say", world.on_say)  # L2: the casualty knocks back when the Scout calls out

    async def on_route(route):
        await bus.publish("route/verified", world.verify(route))

    bus.subscribe("route/proposed", on_route)
    inject.install(world, bus)
    world.responder = responder.attach(world, bus)
    if os.environ.get("AFTERSHOCK_HW") == "1":
        import hw

        world.hw = hw.attach(bus)
    if loop:
        debris.attach(world, bus)  # Y8: world/debris (sim truth, for scoring and the console)
        world.task = asyncio.create_task(run(world, bus))
    return world
