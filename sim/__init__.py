"""sim lane: the MuJoCo world. The hub (coord/hub.py) calls `start(bus)` on startup."""

import asyncio
import logging
import time

from sim import inject, responder, scene
from sim.world import World

RATE_HZ = 10
log = logging.getLogger("sim")


async def run(world, bus, rate_hz=RATE_HZ):
    """Tick the world in real time; publish its events and sensors/scout at rate_hz."""
    dt = 1.0 / rate_hz
    while True:
        started = time.monotonic()
        world.responder.step(dt)      # the Responder (T06) moves on the same tick as the physics
        for topic, data in [*world.tick(dt), ("sensors/scout", world.sensors_message())]:
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

    async def on_route(route):
        await bus.publish("route/verified", world.verify(route))

    bus.subscribe("route/proposed", on_route)
    inject.install(world, bus)
    world.responder = responder.attach(world, bus)
    if loop:
        world.task = asyncio.create_task(run(world, bus))
    return world
