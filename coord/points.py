"""D1: measured depth batches for browsers; private Scout frames stay local."""

import asyncio
import math
import time

RES, MAX_POINTS, PERIOD = 0.05, 2048, 0.5


class PointCloudPublisher:
    def __init__(self, bus, clock=time.monotonic):
        self.bus, self.clock, self.started = bus, clock, clock()
        self.pending = None
        bus.subscribe("sensors/scout", self.on_sensors)
        bus.subscribe("scene/loaded", self.on_scene)

    def on_scene(self, _):
        self.pending = None

    def on_sensors(self, data):
        points = data.get("points")
        if points is None:
            return
        measured, voxels = [], set()
        for point in points[:MAX_POINTS]:
            voxel = tuple(math.floor(value / RES) for value in point)
            if voxel not in voxels:
                voxels.add(voxel)
                measured.append(list(point))  # actual input xyz, never invented voxel centres
        self.pending = {"t": data.get("t", max(0.0, self.clock() - self.started)),
                        "res": RES, "points": measured}
        if data.get("points_from") is not None:
            self.pending["points_from"] = list(data["points_from"])

    async def flush(self):
        frame, self.pending = self.pending, None
        if frame is not None:
            await self.bus.publish("map/points", frame)

    async def run(self):
        while True:
            await self.flush()
            await asyncio.sleep(PERIOD)
