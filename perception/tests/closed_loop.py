"""Closed loop on the backup scene: MuJoCo LiDAR in, Explorer scout/goto out, a kinematic Scout between.

Stands in for sim's T04 driving (0.3 m/s, refuses to come within 0.15 m of anything ahead).
"""

import math

import mujoco
import numpy as np

from perception.explore import Explorer
from perception.fixtures.make_standin import SCENE, Z, lidar
from perception.grid import Grid
from sim import scene

HZ, SPEED, STOP = 10, 0.3, 0.15


class Loop:
    def __init__(self, start=(-0.5, -1.4)):
        self.m = mujoco.MjModel.from_xml_path(str(SCENE))
        self.d = mujoco.MjData(self.m)
        mujoco.mj_forward(self.m, self.d)
        self.grid = Grid()
        self.explorer = Explorer(self.grid)
        self.explorer.on_scene({"blocks": [
            {"id": b["id"], "label": b["label"], "pos": b["pos"], "size": b["size"]}
            for b in scene.blocks(self.m, self.d)]})
        self.pos = [start[0], start[1], Z]
        self.goto = None
        self.t = 0.0
        self.trail = []
        self.reasons = []

    def ahead(self, vec):
        geomid = np.zeros(1, dtype=np.int32)
        dist = mujoco.mj_ray(self.m, self.d, np.array(self.pos), np.array([*vec, 0.0]), None, 1, -1, geomid)
        return dist if dist >= 0 else math.inf

    def step(self):
        data = {"t": self.t, "pose": {"pos": list(self.pos), "yaw": 0.0},
                "lidar": lidar(self.m, self.d, np.array(self.pos)).tolist()}
        self.grid.add_sensors(data)
        self.explorer.on_sensors(data)
        if round(self.t * HZ) % HZ == 0:
            goto = self.explorer.tick(self.t)
            if goto:
                self.goto = goto["target"]
                self.reasons.append(goto["reason"])
        if self.goto:
            dx, dy = self.goto[0] - self.pos[0], self.goto[1] - self.pos[1]
            dist = math.hypot(dx, dy)
            if dist > 1e-6:
                vec = (dx / dist, dy / dist)
                move = min(dist, SPEED / HZ)
                if self.ahead(vec) > STOP + move:
                    self.pos[0] += vec[0] * move
                    self.pos[1] += vec[1] * move
        self.trail.append(tuple(self.pos[:2]))
        self.t = round(self.t + 1 / HZ, 2)

    def run(self, seconds):
        for _ in range(int(seconds * HZ)):
            self.step()


if __name__ == "__main__":  # python -m perception.tests.closed_loop
    loop = Loop()
    loop.run(120)
    for room, (x0, x1) in {"room 1": (-1.45, -0.05), "room 2": (0.05, 1.2), "room 3": (1.3, 2.45)}.items():
        inside = [p for p in loop.trail if x0 < p[0] < x1 and -0.95 < p[1] < 1.45]
        print(room, "visited" if inside else "NOT visited", f"({len(inside)} steps)")
    print("seen", loop.grid.counts(), "reasons", len(loop.reasons), "last:", loop.reasons[-3:])
    print("final", [round(v, 2) for v in loop.pos])
