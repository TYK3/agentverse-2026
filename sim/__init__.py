"""sim lane: the MuJoCo world. The hub (coord/hub.py) calls `start(bus)` on startup."""

import asyncio
import time

from sim import scene
from sim.world import World

RATE_HZ = 10


async def run(world, bus, rate_hz=RATE_HZ):
    """Tick the world in real time and publish sensors/scout at rate_hz."""
    dt = 1.0 / rate_hz
    while True:
        started = time.monotonic()
        world.tick(dt)
        await bus.publish("sensors/scout", world.sensors_message())
        await asyncio.sleep(max(0.0, dt - (time.monotonic() - started)))


async def start(bus, loop=True):
    """Load the backup scene, publish scene/loaded, follow scout/goto, stream sensors/scout."""
    world = World()
    await bus.publish("scene/loaded", scene.scene_loaded(world.m, world.d))
    bus.subscribe("scout/goto", world.goto)
    if loop:
        world.task = asyncio.create_task(run(world, bus))
    return world
