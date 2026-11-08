"""perception lane: the live map, casualties, hazard estimates and Scout exploration. The hub (coord/hub.py) calls `start(bus)` on startup."""

import asyncio
import time

from perception.casualties import PROMPT, Casualties
from perception.cloud import Cloud
from perception.explore import Explorer
from perception.grid import Grid
from perception.hazards import Hazards
from perception.inspect import Inspector, ask_er
from perception.listen import Listener

PERIOD = 0.5          # map/cells and map/casualties (when changed) at 2 Hz
SNAPSHOT_EVERY = 10   # ticks, so a full snapshot every 5 s
EXPLORE_EVERY = 2     # ticks, so a frontier decision every 1 s

_tasks = set()        # keeps the publish loop from being garbage collected


async def start(bus):
    """Map sensors/scout into map/cells (changes at 2 Hz, everything every 5 s) and drive the Scout.

    Hazards come from the Scout's own scans (Z1): depth points (sensors/scout.points) for pile
    stability before a shake, and the LiDAR scan diff after one. scene/loaded block poses and
    world/change moved_blocks are sim truth and are not read.
    """
    grid = Grid()
    explorer = Explorer(grid)
    t0 = time.monotonic()

    def now():
        return time.monotonic() - t0

    bus.subscribe("sensors/scout", grid.add_sensors)
    bus.subscribe("sensors/scout", explorer.on_sensors)
    casualties = Casualties()

    async def vision(b64):
        answer = await asyncio.to_thread(casualties.ask, PROMPT, b64)   # off the event loop
        casualties.dirty |= casualties.on_vision(answer)

    def sensors(data):
        casualties.dirty |= casualties.on_sensors(data)
        b64 = casualties.vision_due(data)
        if b64 is not None:
            _spawn(vision(b64))      # the frame lives only until this call returns

    bus.subscribe("sensors/scout", sensors)
    listener = Listener(grid)  # L2: call out, listen for taps, listen again from a second spot

    async def listen(data):
        for topic, payload in listener.on_sensors(data, now()):
            await bus.publish(topic, payload)

    bus.subscribe("sensors/scout", listen)
    hazards = Hazards(grid, Cloud(grid.res))
    bus.subscribe("sensors/scout", hazards.on_sensors)
    _inspect(bus, now)          # G2: ER points, kept only where the depth points ground them

    def change(data):
        hazards.on_change(data)     # timed on the sensors clock, like the scan diff
        explorer.on_change(data)    # after hazards: it re-visits what was predicted at_risk

    bus.subscribe("world/change", change)
    bus.subscribe("map/hazards", explorer.on_hazards)
    bus.subscribe("scout/goto", lambda d: explorer.on_goto(d, now()))
    bus.subscribe("gate/decision", lambda d: explorer.on_decision(d, now()))
    _spawn(_publish(bus, grid, explorer, casualties, hazards, now))
    return grid


def _inspect(bus, now):
    try:
        from coord import gem
    except ImportError:
        return None
    inspector = Inspector()
    if gem.MODE == "off":
        gem.mark_stand_in("spatial_inspection")    # no ER points: the Explorer's own frontiers only

    async def er(pose, b64):
        text, receipt, model = await asyncio.to_thread(ask_er, gem, b64)    # off the event loop
        if text is not None:
            for topic, payload in inspector.goals(pose, text, receipt=receipt, model=model, now=now()):
                await bus.publish(topic, payload)

    def frame(data):
        inspector.keep_points(data, now())
        if gem.MODE != "off" and inspector.due(data, now()):
            inspector.last_ask = now()
            cam = data["camera"]
            _spawn(er(data["pose"], cam["b64"] if isinstance(cam, dict) else cam))

    bus.subscribe("sensors/scout", frame)
    return inspector


def _spawn(coro):
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def _publish(bus, grid, explorer, casualties, hazards, now):
    tick, diffs = 0, 0
    while True:
        await asyncio.sleep(PERIOD)
        tick += 1
        t = now()
        if tick % SNAPSHOT_EVERY == 0:
            await bus.publish("map/cells", grid.snapshot(t))
        elif grid.changed:
            await bus.publish("map/cells", grid.delta(t))
        changed = list(grid.appeared) + list(grid.cleared)
        if len(changed) != diffs:          # the scan diff found something new: look closer
            explorer.on_diff(changed[diffs:] if len(changed) > diffs else changed)
            diffs = len(changed)
        msg = hazards.update(grid.t)
        if msg is not None:
            await bus.publish("map/hazards", msg)
        if casualties.dirty:
            casualties.dirty = False
            await bus.publish("map/casualties", casualties.message())
        if tick % EXPLORE_EVERY == 0:
            goto = explorer.tick(t)
            if goto:
                await bus.publish("scout/goto", goto)
