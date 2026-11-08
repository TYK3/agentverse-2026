"""L4: the Scout drives between levels (L1 -> ground -> B1) on real ramps, never teleported.

`LevelWorld` is `sim.world.World` on sim/scenes/levels.xml with one change to how the Scout moves:
  - its height comes only from the floor under it. Before each step a ray is cast straight down
    from just above the Scout, and the Scout rides RIDE above whatever it hits.
  - a step whose floor is more than MAX_RISE above or below the current one is refused (a drop, a
    kerb or a wall face): the Scout stops and reports `blocked`. Ramps up to about 30 degrees pass.
  - `scout/goto` targets are honoured in 3D: the Scout is `arrived` only when it is over the target
    (x, y) AND its floor is within LEVEL_TOL of the target z. Over the right spot on the wrong
    level it reports `blocked`, because it cannot change level where it stands.

Everything else (sensors, sensors/scout payload, verify, inject) is World's. The hub's sim lane is
unchanged; run this scene with `python -m sim.levels` or `await sim.levels.start(bus)`.
"""

import asyncio
import math
import time

import numpy as np

from sim import scene, sensors
from sim.world import ARRIVE, SPEED, World

LEVELS = scene.SCENES / "levels.xml"
RIDE = 0.075        # sensor origin above the floor, as in backup.xml
PROBE = 0.25        # the support ray starts this far above the current floor (under any slab above)
MAX_RISE = 0.6      # max floor change per metre driven (tan 31 deg); ramps here are 16.7 deg
STEP_SLACK = 0.004  # metres of floor change always allowed per step (ramp seams, float noise)
LEVEL_TOL = 0.10    # metres: the Scout's floor must be this close to a target's z to have arrived
SUBSTEP = 0.01      # metres: long steps are checked in pieces so a drop between samples is not missed


class LevelWorld(World):
    def __init__(self, path=LEVELS, seed=0, render=True):
        super().__init__(path, seed=seed, render=render)
        self.target_z = None
        self.floor_z = self._floor_at(self.pos[:2], self.pos[2] - RIDE + PROBE)
        if self.floor_z is None:
            raise ValueError("the Scout starts over no floor")
        self._set_z(self.floor_z)
        self.trace = [(self.t, *self.pos)]   # every pose, for the no-teleport check

    # ---- support ----------------------------------------------------------------
    def _floor_at(self, xy, z_from):
        """Height of the first surface straight below (x, y) from z_from, or None if there is none."""
        dist, _ = sensors._ray(self.m, self.d, [xy[0], xy[1], z_from], [0.0, 0.0, -1.0],
                               self.scout, sensors.SENSE_GROUPS)
        return None if dist < 0 else z_from - dist

    def _set_z(self, floor_z):
        self.floor_z = floor_z
        self.d.mocap_pos[self.scout_mocap][2] = floor_z + RIDE

    # ---- commands ----------------------------------------------------------------
    def goto(self, msg):
        super().goto(msg)
        target = msg["target"]
        self.target_z = float(target[2]) if len(target) > 2 else None

    def _on_target_level(self):
        return self.target_z is None or abs(self.floor_z - self.target_z) <= LEVEL_TOL

    def _drive(self, dt):
        if self.state != "moving" or self.target is None:
            return
        delta = self.target - self.pos[:2]
        dist = float(np.linalg.norm(delta))
        if dist < ARRIVE:
            self.state = "arrived" if self._on_target_level() else "blocked"
            return
        heading = math.atan2(delta[1], delta[0])
        step = min(SPEED * dt, dist)
        self._set_pose(self.pos[:2], heading)
        if not self._free_ahead(heading, step):
            self.state = "blocked"
            return
        unit = delta / dist
        xy, floor = self.pos[:2], self.floor_z
        n = max(1, math.ceil(step / SUBSTEP))
        for _ in range(n):
            nxt = xy + unit * (step / n)
            z = self._floor_at(nxt, floor + PROBE)
            if z is None or abs(z - floor) > MAX_RISE * step / n + STEP_SLACK:
                self.state = "blocked"          # a drop or a kerb: stay where the last good floor was
                break
            xy, floor = nxt, z
        self._set_pose(xy, heading)
        self._set_z(floor)

    def tick(self, dt=0.1):
        events = super().tick(dt)
        self.trace.append((self.t, *self.pos))
        return events

    def level(self):
        """Name of the level the Scout is on: L1, ground, B1 or ramp."""
        for name, z in (("L1", 0.6), ("ground", 0.0), ("B1", -0.6)):
            if abs(self.floor_z - z) < 0.02:
                return name
        return "ramp"


def max_jump(trace):
    """Largest straight-line move between two consecutive poses in a trace (metres)."""
    p = np.asarray([row[1:] for row in trace], float)
    return float(np.max(np.linalg.norm(np.diff(p, axis=0), axis=1))) if len(p) > 1 else 0.0


async def run(world, bus, rate_hz=10):
    dt = 1.0 / rate_hz
    while True:
        started = time.monotonic()
        for topic, data in world.tick(dt):
            await bus.publish(topic, data)
        await bus.publish("sensors/scout", world.sensors_message(camera=False))
        await asyncio.sleep(max(0.0, dt - (time.monotonic() - started)))


async def start(bus, loop=True):
    """The multi-level scene on the bus: scene/loaded, scout/goto (3D), sensors/scout at 10 Hz."""
    world = LevelWorld(render=False)
    bus.subscribe("scout/goto", world.goto)
    await bus.publish("scene/loaded", scene.scene_loaded(world.m, world.d))
    if loop:
        world.task = asyncio.create_task(run(world, bus))
    return world


if __name__ == "__main__":
    w = LevelWorld(render=False)
    print(f"Scout on {w.level()} at {np.round(w.pos, 3).tolist()}")
