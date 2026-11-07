"""perception lane: the live map and Scout exploration. The hub (coord/hub.py) calls `start(bus)` on startup."""

import asyncio
import time

from perception.explore import Explorer
from perception.grid import Grid

PERIOD = 0.5          # map/cells at 2 Hz
SNAPSHOT_EVERY = 10   # ticks, so a full snapshot every 5 s
EXPLORE_EVERY = 2     # ticks, so a frontier decision every 1 s

_tasks = set()        # keeps the publish loop from being garbage collected


async def start(bus):
    """Map sensors/scout into map/cells (changes at 2 Hz, everything every 5 s) and drive the Scout."""
    grid = Grid()
    explorer = Explorer(grid)
    t0 = time.monotonic()

    def now():
        return time.monotonic() - t0

    bus.subscribe("sensors/scout", grid.add_sensors)
    bus.subscribe("sensors/scout", explorer.on_sensors)
    bus.subscribe("scene/loaded", explorer.on_scene)
    bus.subscribe("map/hazards", explorer.on_hazards)
    bus.subscribe("world/change", explorer.on_change)
    bus.subscribe("scout/goto", lambda d: explorer.on_goto(d, now()))
    bus.subscribe("gate/decision", lambda d: explorer.on_decision(d, now()))
    task = asyncio.create_task(_publish(bus, grid, explorer, now))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return grid


async def _publish(bus, grid, explorer, now):
    tick = 0
    while True:
        await asyncio.sleep(PERIOD)
        tick += 1
        t = now()
        if tick % SNAPSHOT_EVERY == 0:
            await bus.publish("map/cells", grid.snapshot(t))
        elif grid.changed:
            await bus.publish("map/cells", grid.delta(t))
        if tick % EXPLORE_EVERY == 0:
            goto = explorer.tick(t)
            if goto:
                await bus.publish("scout/goto", goto)
