"""Closed loop on the backup scene: MuJoCo LiDAR (and depth points) in, Explorer scout/goto out, a kinematic
Scout between.

Stands in for sim's T04 driving (0.3 m/s, refuses to come within 0.15 m of anything ahead) and for the
Y9 depth camera (`depth_points`: rays from the Scout's camera, 0.15 m ahead and 0.18 m up, 75 x 60
degrees, sent with `points_from`). Perception
gets only what a real Scout would: its pose, LiDAR ranges and depth points. Block poses are used here,
by the test world, to move blocks in the aftershock and to score the result, never by perception.
"""

import math

import mujoco
import numpy as np

from perception.cloud import Cloud
from perception.explore import Explorer
from perception.fixtures.make_standin import SCENE, Z
from perception.grid import Grid
from perception.hazards import Hazards
from sim.sensors import SENSE_GROUPS

HZ, SPEED, STOP = 10, 0.3, 0.15
CAM_FWD, CAM_Z, CAM_H, CAM_V, COLS, ROWS = 0.15, 0.18, math.radians(75), math.radians(60), 24, 18
DEPTH_RANGE = 4.0
DEPTH_EVERY = 5      # frames: depth points at 2 Hz

# Where the aftershock leaves the blocks that move (the test world's truth): b10 slides off b8 and lies
# flat, b8 topples west into room 2, b11 is shoved 0.3 m north out of the room 2/3 gap.
FALLEN = {
    "b10": ([0.85, -0.5, 0.03], [1, 0, 0, 0]),
    "b8": ([0.70, -0.3225, 0.05], [math.cos(math.pi / 4), 0, math.sin(math.pi / 4), 0]),
    "b11": ([1.25, 0.75, 0.08], [1, 0, 0, 0]),
}


def lidar(m, d, origin, n=360, max_range=6.0):
    """360 horizontal rays like sim/sensors.py: robot geoms (group 3) are not seen."""
    ranges = np.full(n, max_range)
    geomid = np.zeros(1, dtype=np.int32)
    for k in range(n):
        a = 2 * np.pi * k / n
        dist = mujoco.mj_ray(m, d, origin, np.array([np.cos(a), np.sin(a), 0.0]), SENSE_GROUPS, 1, -1, geomid)
        if dist >= 0:
            ranges[k] = min(dist, max_range)
    return ranges


def footprint(m, d, name, res=0.05):
    """Plan cells under block `name` as it lies now (its rotated box's x-y extent): truth, for scoring only."""
    g = m.body_geomadr[m.body(name).id]
    rot, centre, size = d.geom_xmat[g].reshape(3, 3), d.geom_xpos[g], m.geom_size[g]
    corners = np.array([centre + rot @ (np.array([sx, sy, sz]) * size)
                        for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)])
    lo, hi = corners.min(0), corners.max(0)
    return {(i, j) for i in range(math.floor(lo[0] / res), math.floor((hi[0] - 1e-9) / res) + 1)
            for j in range(math.floor(lo[1] / res), math.floor((hi[1] - 1e-9) / res) + 1)}


def camera(pos, yaw):
    return [pos[0] + CAM_FWD * math.cos(yaw), pos[1] + CAM_FWD * math.sin(yaw), CAM_Z]


def depth_points(m, d, pos, yaw):
    """Scene-frame points the Scout's depth camera would return, looking along `yaw`."""
    origin = np.array(camera(pos, yaw))
    geomid = np.zeros(1, dtype=np.int32)
    out = []
    for r in range(ROWS):
        el = CAM_V * (0.5 - (r + 0.5) / ROWS)
        for c in range(COLS):
            az = yaw + CAM_H * (0.5 - (c + 0.5) / COLS)
            vec = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
            dist = mujoco.mj_ray(m, d, origin, vec, SENSE_GROUPS, 1, -1, geomid)
            if 0 <= dist <= DEPTH_RANGE:
                out.append([round(float(v), 3) for v in origin + dist * vec])
    return out


class Loop:
    def __init__(self, start=(-0.5, -1.4), depth=True):
        self.m = mujoco.MjModel.from_xml_path(str(SCENE))
        self.d = mujoco.MjData(self.m)
        mujoco.mj_forward(self.m, self.d)
        self.grid = Grid()
        self.cloud = Cloud()
        self.hazards = Hazards(self.grid, self.cloud)
        self.explorer = Explorer(self.grid)
        self.depth = depth
        self.pos = [start[0], start[1], Z]
        self.yaw = math.pi / 2
        self.goto = None
        self.t = 0.0
        self.frame = 0
        self.trail = []
        self.reasons = []
        self.diffs = 0

    def ahead(self, vec):
        geomid = np.zeros(1, dtype=np.int32)
        dist = mujoco.mj_ray(self.m, self.d, np.array(self.pos), np.array([*vec, 0.0]), None, 1, -1, geomid)
        return dist if dist >= 0 else math.inf

    def step(self):
        data = {"t": self.t, "pose": {"pos": list(self.pos), "yaw": self.yaw},
                "lidar": lidar(self.m, self.d, np.array(self.pos)).tolist()}
        if self.depth and self.frame % DEPTH_EVERY == 0:
            data["points"] = depth_points(self.m, self.d, self.pos, self.yaw)
            data["points_from"] = camera(self.pos, self.yaw)
        self.grid.add_sensors(data)
        self.hazards.on_sensors(data)
        self.explorer.on_sensors(data)
        if round(self.t * HZ) % HZ == 0:      # what perception.start's 2 Hz loop does, here at 1 Hz
            changed = list(self.grid.appeared) + list(self.grid.cleared)
            if len(changed) != self.diffs:
                self.explorer.on_diff(changed[self.diffs:] if len(changed) > self.diffs else changed)
                self.diffs = len(changed)
            msg = self.hazards.update(self.t)
            if msg is not None:
                self.explorer.on_hazards(msg)
            goto = self.explorer.tick(self.t)
            if goto:
                self.goto = goto["target"]
                self.reasons.append(goto["reason"])
        if self.goto:
            dx, dy = self.goto[0] - self.pos[0], self.goto[1] - self.pos[1]
            dist = math.hypot(dx, dy)
            if dist > 1e-6:
                vec = (dx / dist, dy / dist)
                self.yaw = math.atan2(dy, dx)
                move = min(dist, SPEED / HZ)
                if self.ahead(vec) > STOP + move:
                    self.pos[0] += vec[0] * move
                    self.pos[1] += vec[1] * move
        self.trail.append(tuple(self.pos[:2]))
        self.frame += 1
        self.t = round(self.t + 1 / HZ, 2)

    def aftershock(self, moved=tuple(FALLEN)):
        """The test world moves `moved` to where they fall; perception hears only that a shake happened."""
        for name in moved:
            adr = self.m.joint(self.m.body(name).jntadr[0]).qposadr[0]
            pos, quat = FALLEN[name]
            self.d.qpos[adr:adr + 3] = pos
            self.d.qpos[adr + 3:adr + 7] = quat
        mujoco.mj_forward(self.m, self.d)
        change = {"kind": "aftershock", "t": self.t, "moved_blocks": list(moved)}
        self.hazards.on_change(change, self.t)
        self.explorer.on_change(change)

    def watch(self, x, y, yaw, frames, move=None):
        """Park the Scout at (x, y) facing `yaw` for `frames` steps; `move(m, d)` changes the world each step."""
        self.goto = None
        self.explorer.hold = ([x, y, Z], math.inf, None, 0.0)   # as if the planner held it there
        for _ in range(frames):
            if move:
                move(self.m, self.d)
                mujoco.mj_forward(self.m, self.d)
            self.pos[:2], self.yaw = [x, y], yaw
            self.step()
        self.pos[:2], self.yaw = [x, y], yaw

    def run(self, seconds):
        for _ in range(int(seconds * HZ)):
            self.step()


if __name__ == "__main__":  # python -m perception.tests.closed_loop
    loop = Loop()
    loop.run(90)
    for room, (x0, x1) in {"room 1": (-1.45, -0.05), "room 2": (0.05, 1.2), "room 3": (1.3, 2.45)}.items():
        inside = [p for p in loop.trail if x0 < p[0] < x1 and -0.95 < p[1] < 1.45]
        print(room, "visited" if inside else "NOT visited", f"({len(inside)} steps)")
    print("at_risk before:", sorted(ij for ij, (s, _) in loop.hazards.labels.items() if s == "at_risk"))
    loop.aftershock()
    loop.run(30)
    print("collapsed after:", len([1 for s, _ in loop.hazards.labels.values() if s == "collapsed"]),
          "cleared:", len(loop.grid.cleared), "appeared:", len(loop.grid.appeared))
    print("reasons", loop.reasons[-5:])
