"""perception lane: the live map. The hub (coord/hub.py) calls `start(bus)` on startup."""

import asyncio
import time

from perception.grid import Grid

PERIOD = 0.5          # map/cells at 2 Hz
SNAPSHOT_EVERY = 10   # ticks, so a full snapshot every 5 s

_tasks = set()        # keeps the publish loop from being garbage collected


async def start(bus):
    """Build the map from sensors/scout and publish map/cells: changes at 2 Hz, everything every 5 s."""
    grid = Grid()
    bus.subscribe("sensors/scout", grid.add_sensors)
    task = asyncio.create_task(_publish(bus, grid))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return grid


async def _publish(bus, grid):
    t0 = time.monotonic()
    tick = 0
    while True:
        await asyncio.sleep(PERIOD)
        tick += 1
        t = time.monotonic() - t0
        if tick % SNAPSHOT_EVERY == 0:
            await bus.publish("map/cells", grid.snapshot(t))
        elif grid.changed:
            await bus.publish("map/cells", grid.delta(t))
