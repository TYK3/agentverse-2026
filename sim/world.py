"""The running sim world (T04): MuJoCo physics plus the kinematic Scout and its sensors.

Other sim tasks (aftershock T05, physics check T06) work on the same `World`: `world.m`,
`world.d`, `world.t` and `world.tick(dt)`.
"""

import math

import mujoco
import numpy as np

from sim import scene, sensors

SPEED = 0.3            # m/s
CLEARANCE = 0.15       # metres of free space the Scout needs ahead before it moves
HALF_WIDTH = 0.08      # Scout chassis half width; side rays check the corners
ARRIVE = 0.02          # metres


class World:
    def __init__(self, path=scene.BACKUP, seed=0, render=True):
        self.m, self.d = scene.load(path)
        self.t = 0.0
        self.rng = np.random.default_rng(seed)
        self.scout = self.m.body("scout").id
        self.scout_mocap = int(self.m.body_mocapid[self.scout])
        self.casualty_geom = self.m.geom("c1_g").id
        self.target = None          # [x, y] the Scout is driving to
        self.reason = ""
        self.state = "idle"         # idle | moving | arrived | blocked
        self.renderer = sensors.make_renderer(self.m) if render else None

    # ---- Scout pose --------------------------------------------------------------
    @property
    def pos(self):
        return self.d.mocap_pos[self.scout_mocap].copy()

    @property
    def yaw(self):
        w, _, _, z = self.d.mocap_quat[self.scout_mocap]
        return 2.0 * math.atan2(z, w)

    def _set_pose(self, xy, yaw):
        self.d.mocap_pos[self.scout_mocap][:2] = xy
        self.d.mocap_quat[self.scout_mocap] = [math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2)]

    # ---- commands ----------------------------------------------------------------
    def goto(self, msg):
        """Handle a scout/goto message: {"target":[x,y,z], "reason":"..."}."""
        self.target = np.asarray(msg["target"][:2], float)
        self.reason = msg.get("reason", "")
        self.state = "moving"

    def _free_ahead(self, heading, step):
        """True if nothing is within CLEARANCE + step ahead along the centre line or either side."""
        fwd = np.array([math.cos(heading), math.sin(heading), 0.0])
        side = np.array([-fwd[1], fwd[0], 0.0])
        need = CLEARANCE + step
        for offset in (0.0, HALF_WIDTH, -HALF_WIDTH):
            dist, _ = sensors._ray(self.m, self.d, self.pos + side * offset, fwd, self.scout)
            if 0 <= dist < need:
                return False
        return True

    def _drive(self, dt):
        if self.state != "moving" or self.target is None:
            return
        delta = self.target - self.pos[:2]
        dist = float(np.linalg.norm(delta))
        if dist < ARRIVE:
            self.state = "arrived"
            return
        heading = math.atan2(delta[1], delta[0])
        step = min(SPEED * dt, dist)
        self._set_pose(self.pos[:2], heading)
        if not self._free_ahead(heading, step):
            self.state = "blocked"
            return
        self._set_pose(self.pos[:2] + delta / dist * step, heading)

    # ---- time --------------------------------------------------------------------
    def tick(self, dt=0.1):
        """Advance physics and the Scout by dt seconds."""
        self._drive(dt)
        for _ in range(max(1, round(dt / self.m.opt.timestep))):
            mujoco.mj_step(self.m, self.d)
        self.t = round(self.t + dt, 6)

    # ---- sensors -----------------------------------------------------------------
    def sensors_message(self, camera=True):
        """Payload for sensors/scout. `camera` adds a base64 JPEG frame when a renderer exists."""
        origin, yaw = self.pos, self.yaw
        casualty = self.d.geom_xpos[self.casualty_geom].copy()
        hit, _ = sensors.first_hit(self.m, self.d, origin, casualty, self.scout)
        in_sight = hit == self.casualty_geom
        walls = 0 if in_sight else sensors.walls_between(self.m, self.d, origin, casualty, self.scout, self.casualty_geom)
        visible = in_sight and float(np.linalg.norm((casualty - origin)[:2])) <= sensors.THERMAL_RANGE
        data = {
            "t": round(self.t, 2),
            "pose": {"pos": [round(float(v), 3) for v in origin], "yaw": round(yaw, 3)},
            "lidar": [round(float(r), 3) for r in sensors.lidar(self.m, self.d, origin, self.scout)],
            "thermal": np.round(sensors.thermal(origin, yaw, casualty, visible), 2).tolist(),
            "acoustic": sensors.acoustic(origin, yaw, casualty, walls, self.rng),
            "motion": {"state": self.state, "target": None if self.target is None else [round(float(v), 3) for v in self.target]},
        }
        if camera:
            frame = sensors.camera_jpeg(self.d, self.renderer)
            if frame is not None:
                data["camera"] = {"format": "jpeg", "b64": frame}
        return data
