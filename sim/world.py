"""The running sim world (T04, T05): MuJoCo physics, the kinematic Scout and its sensors, the live
aftershock and the injected block.

Other sim tasks (Responder T06) work on the same `World`: `world.m`, `world.d`, `world.t`,
`world.tick(dt)`, and `world.shaking` (the Responder freezes while it is true and drops its move).
`tick` returns the events to publish, as (topic, data) pairs.
"""

import math
import re

import mujoco
import numpy as np

from sim import aftershock, breakage, scene, sensors

SPEED = 0.3            # m/s
CLEARANCE = 0.15       # metres of free space the Scout needs ahead before it moves
HALF_WIDTH = 0.08      # Scout chassis half width; side rays check the corners
ARRIVE = 0.02          # metres
WARMUP_S = 0.5         # seconds of settling, breaking disarmed, before a breakable scene starts
LAND = 1.0             # seconds an injected block gets to fall and settle before world/change


def casualties(m):
    """[(name, geom id, voice)] for every casualty geom c<n>_g, in number order. `voice` (0 silent ..
    1 calling out) comes from the scene's <numeric name="voice_c<n>"> and defaults to 1."""
    out = []
    for g in range(m.ngeom):
        match = re.fullmatch(r"(c\d+)_g", mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or "")
        if match:
            name = match.group(1)
            k = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_NUMERIC, "voice_" + name)
            voice = float(m.numeric_data[m.numeric_adr[k]]) if k >= 0 else 1.0
            out.append((name, g, voice))
    return sorted(out, key=lambda c: int(c[0][1:]))


class World:
    def __init__(self, path=scene.BACKUP, seed=0, render=True):
        self.m, self.d = scene.load(path)
        self.t = 0.0
        self.rng = np.random.default_rng(seed)
        self._scout_model()
        self.breaker = breakage.Breaker(self.m)    # no-op unless the scene has weld limits (building)
        if self.breaker.active:
            # The first steps load every weld at once; that spike is not damage. Settle before arming.
            for _ in range(round(WARMUP_S / self.m.opt.timestep)):
                mujoco.mj_step(self.m, self.d)
        self.casualties = casualties(self.m)   # [(name, geom id, voice)], c1 first
        self.casualty_geom = self.casualties[0][1]
        self.target = None          # [x, y] the Scout is driving to
        self.reason = ""
        self.state = "idle"         # idle | moving | arrived | blocked
        self.renderer = sensors.make_renderer(self.m) if render else None
        self.ground = aftershock.ground_mocap(self.m)
        self.ground_base = self.d.mocap_pos[self.ground].copy()
        self.shake_t0 = None        # world time the live aftershock began, or None
        self.shake_start = None     # block positions when it began
        self.events = []            # (topic, data) produced since the last tick
        self.landing = None         # (world time, name) when an injected block will have landed
        self.refresh_unstable()

    def _scout_model(self):
        """Small backup Scout (body `scout`, origin = LiDAR) or the true-scale LIMO (`scout/scout`, sim/robots:
        origin on the ground, LiDAR site above it, camera `depth_cam`)."""
        m = self.m
        prefix = "" if mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "scout") >= 0 else "scout/"
        self.scout = m.body(prefix + "scout").id
        self.scout_mocap = int(m.body_mocapid[self.scout])
        site = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, prefix + "lidar")
        if site >= 0:                                        # true scale: sizes from the robot spec
            half_len, half_w = 0.161, 0.11
            self.sensor_offset = m.site_pos[site].copy()
            self.clearance, self.half_width, self.drive_z = half_len + CLEARANCE, half_w, 0.1
            self.camera_name = prefix + "depth_cam"
        else:
            self.sensor_offset = np.zeros(3)
            self.clearance, self.half_width, self.drive_z = CLEARANCE, HALF_WIDTH, 0.0
            self.camera_name = "scout_cam"

    @property
    def sensor_origin(self):
        """Where the LiDAR, thermal and microphones sit: the Scout origin plus the LiDAR offset, turned by yaw."""
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        x, y, z = self.sensor_offset
        return self.pos + np.array([c * x - s * y, s * x + c * y, z])

    # ---- physics route check ----------------------------------------------------
    def refresh_unstable(self):
        """Recompute (on a copy) which cells a further aftershock would make unsafe."""
        self.unstable, self.would_move = aftershock.unstable_xy(self.m, self.d)

    def verify(self, route):
        """route/verified payload for a route/proposed message (a cached lookup, well under 1 s)."""
        return aftershock.verify(route, self.unstable, self.would_move)

    # ---- the live aftershock and the unscripted change --------------------------
    @property
    def shaking(self):
        return self.shake_t0 is not None

    def trigger_aftershock(self):
        """Start shaking the live world. world/change goes out when it has settled (3 s of world time)."""
        if self.shaking:
            return False
        self.shake_t0 = self.t
        ids = aftershock.candidate_blocks(self.m)
        self.shake_start = (ids, self.d.xpos[ids].copy())
        return True

    def _finish_aftershock(self):
        ids, start = self.shake_start
        moved = [aftershock.body_name(self.m, i) for i, p in zip(ids, start, strict=True)
                 if np.linalg.norm(self.d.xpos[i] - p) > aftershock.MOVED]
        self.shake_t0 = self.shake_start = None
        self.d.mocap_pos[self.ground] = self.ground_base
        self.refresh_unstable()
        self.events.append(("world/change", {"kind": "aftershock", "t": round(self.t, 2), "moved_blocks": moved}))

    def inject(self, cell):
        """Drop the spare block on grid cell [i, j, k] (the integration runner's hook). Returns its name."""
        res = aftershock.RES
        return self.add_block([(cell[0] + 0.5) * res, (cell[1] + 0.5) * res, 0.3])

    def add_block(self, pos):
        """Drop the spare rubble block at pos [x, y, z] (z is its centre height). Returns its name or None."""
        spare = [b for b in aftershock.spare_ids(self.m) if self.m.body_gravcomp[b] == 1]
        if not spare:
            return None
        b = spare[0]
        g = self.m.body_geomadr[b]
        self.m.body_gravcomp[b] = 0
        self.m.geom_contype[g], self.m.geom_conaffinity[g] = 1, 3       # 3: also hits braced pieces (tower)
        self.m.body_contype[b], self.m.body_conaffinity[b] = 1, 3      # the broad phase filters on these too
        adr = self.m.jnt_qposadr[self.m.body_jntadr[b]]
        vadr = self.m.jnt_dofadr[self.m.body_jntadr[b]]
        z = max(float(pos[2]), float(self.m.geom_size[g][2]) + 0.005)
        self.d.qpos[adr:adr + 7] = [pos[0], pos[1], z, 1, 0, 0, 0]
        self.d.qvel[vadr:vadr + 6] = 0
        mujoco.mj_forward(self.m, self.d)
        name = aftershock.body_name(self.m, b)
        self.landing = (self.t + LAND, name)    # world/change once it has landed (see tick)
        return name

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
        need = self.clearance + step
        base = self.pos + np.array([0.0, 0.0, self.drive_z])
        for offset in (0.0, self.half_width, -self.half_width):
            dist, _ = sensors._ray(self.m, self.d, base + side * offset, fwd, self.scout)
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
        """Advance physics and the Scout by dt seconds. Returns the events to publish."""
        self._drive(dt)
        h = self.m.opt.timestep
        for n in range(max(1, round(dt / h))):
            if self.shaking:
                offset = aftershock.shake_offset(self.t + n * h - self.shake_t0)
                self.d.mocap_pos[self.ground] = self.ground_base + offset
            mujoco.mj_step(self.m, self.d)
            self.breaker.step(self.m, self.d)
        self.t = round(self.t + dt, 6)
        if self.shaking and self.t - self.shake_t0 >= aftershock.DURATION - 1e-9:
            self._finish_aftershock()
        if self.landing and self.t >= self.landing[0] - 1e-9:
            name, self.landing = self.landing[1], None
            self.refresh_unstable()
            self.events.append(("world/change", {"kind": "block_added", "t": round(self.t, 2), "moved_blocks": [name]}))
        events, self.events = self.events, []
        return events

    # ---- sensors -----------------------------------------------------------------
    def sensors_message(self, camera=True):
        """Payload for sensors/scout. `camera` adds a base64 JPEG frame when a renderer exists."""
        origin, yaw = self.sensor_origin, self.yaw
        heard, thermal = [], None
        for _name, geom, voice in self.casualties:
            casualty = self.d.geom_xpos[geom].copy()
            hit, _ = sensors.first_hit(self.m, self.d, origin, casualty, self.scout)
            in_sight = hit == geom
            walls = 0 if in_sight else sensors.walls_between(self.m, self.d, origin, casualty, self.scout, geom)
            visible = in_sight and float(np.linalg.norm((casualty - origin)[:2])) <= sensors.THERMAL_RANGE
            grid = sensors.thermal(origin, yaw, casualty, visible)
            thermal = grid if thermal is None else thermal + (grid - 0.1)
            heard.append(sensors.acoustic(origin, yaw, casualty, walls, self.rng, voice=voice))
        loudest = max(heard, key=lambda a: a["level"])     # the contract carries one bearing: the loudest
        data = {
            "t": round(self.t, 2),
            "pose": {"pos": [round(float(v), 3) for v in origin], "yaw": round(yaw, 3)},
            "lidar": [round(float(r), 3) for r in sensors.lidar(self.m, self.d, origin, self.scout)],
            "thermal": np.round(np.clip(thermal, 0.0, 1.0), 2).tolist(),
            "acoustic": loudest,
            "motion": {"state": self.state, "target": None if self.target is None else [round(float(v), 3) for v in self.target]},
        }
        if camera:
            frame = sensors.camera_jpeg(self.d, self.renderer, name=self.camera_name)
            if frame is not None:
                data["camera"] = {"format": "jpeg", "b64": frame}
        return data
