"""The running sim world (T04, T05): MuJoCo physics, the kinematic Scout and its sensors, the live
aftershock and the injected block.

Other sim tasks (Responder T06) work on the same `World`: `world.m`, `world.d`, `world.t`,
`world.tick(dt)`, and `world.shaking` (the Responder freezes while it is true and drops its move).
`tick` returns the events to publish, as (topic, data) pairs.
"""

import math

import mujoco
import numpy as np

from sim import aftershock, scene, sensors

SPEED = 0.3            # m/s
CLEARANCE = 0.15       # metres of free space the Scout needs ahead before it moves
HALF_WIDTH = 0.08      # Scout chassis half width; side rays check the corners
ARRIVE = 0.02          # metres
LAND = 1.0             # seconds an injected block gets to fall and settle before world/change
HEAR_CALL_M = 6.0      # the casualty hears the Scout calling within this range (L2)
TAP_DELAY_S = 1.0      # reaction time before they start knocking
TAP_S = 6.0            # how long they knock after each call


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
        self.ground = aftershock.ground_mocap(self.m)
        self.ground_base = self.d.mocap_pos[self.ground].copy()
        self.shake_t0 = None        # world time the live aftershock began, or None
        self.shake_start = None     # block positions when it began
        self.events = []            # (topic, data) produced since the last tick
        self.landing = None         # (world time, name) when an injected block will have landed
        self.tapping = None         # (from, until) world times the casualty knocks back (L2)
        self.refresh_unstable()

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
        self.m.geom_contype[g] = self.m.geom_conaffinity[g] = 1
        self.m.body_contype[b] = self.m.body_conaffinity[b] = 1      # the broad phase filters on these too
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
        """Advance physics and the Scout by dt seconds. Returns the events to publish."""
        self._drive(dt)
        h = self.m.opt.timestep
        for n in range(max(1, round(dt / h))):
            if self.shaking:
                offset = aftershock.shake_offset(self.t + n * h - self.shake_t0)
                self.d.mocap_pos[self.ground] = self.ground_base + offset
            mujoco.mj_step(self.m, self.d)
        self.t = round(self.t + dt, 6)
        if self.shaking and self.t - self.shake_t0 >= aftershock.DURATION - 1e-9:
            self._finish_aftershock()
        if self.landing and self.t >= self.landing[0] - 1e-9:
            name, self.landing = self.landing[1], None
            self.refresh_unstable()
            self.events.append(("world/change", {"kind": "block_added", "t": round(self.t, 2), "moved_blocks": [name]}))
        events, self.events = self.events, []
        return events

    # ---- the casualty answers a call (L2) ------------------------------------------
    def on_say(self, msg):
        """A `say` to the casualty, spoken by the Scout: if the casualty can hear it, they tap.

        Heard when the Scout is within HEAR_CALL_M and at most two walls away; they start after a
        short reaction time and knock for TAP_S seconds.
        """
        if msg.get("to") != "casualty":
            return
        origin = self.pos
        casualty = self.d.geom_xpos[self.casualty_geom].copy()
        if float(np.linalg.norm((casualty - origin)[:2])) > HEAR_CALL_M:
            return
        hit, _ = sensors.first_hit(self.m, self.d, origin, casualty, self.scout)
        walls = 0 if hit == self.casualty_geom else sensors.walls_between(
            self.m, self.d, origin, casualty, self.scout, self.casualty_geom)
        if walls <= 2:
            self.tapping = (self.t + TAP_DELAY_S, self.t + TAP_DELAY_S + TAP_S)

    @property
    def is_tapping(self):
        return self.tapping is not None and self.tapping[0] <= self.t < self.tapping[1]

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
            "acoustic": sensors.acoustic(origin, yaw, casualty, walls, self.rng, tapping=self.is_tapping),
            "motion": {"state": self.state, "target": None if self.target is None else [round(float(v), 3) for v in self.target]},
        }
        if camera:
            frame = sensors.camera_jpeg(self.d, self.renderer)
            if frame is not None:
                data["camera"] = {"format": "jpeg", "b64": frame}
        return data
