"""Debris tracking (Y8): where every loose piece is, what just fell, and how stable each pile is.

This is **sim truth**, for scoring and the console, never an input to perception: the robots must
sense the world themselves (demo focus, 7 Nov). Perception's scan-based hazards (Z1) are scored
against `DebrisTracker.risk_cells()`.

- `DebrisTracker(m)` tracks every free body that is not a robot, a supply or a casualty
  (so it covers the backup scene's b* blocks, injected x* blocks and Y1's generated rubble).
- `sample(d, t)` (call a few times a second) returns events:
  `moved` (started moving), `fell` (dropped more than FALL_DROP while moving), `settled` (stopped).
- `stacks(d)` groups touching pieces into piles and scores each one 0..1 from tilt, support
  (how far the centre of mass sits from what holds it up) and recent motion.
- `message(d, t, events)` is the `world/debris` payload; `risk_cells(d)` lists the grid columns a
  pile could fall onto if it went (secondary-fall risk), in perception's grid.
- `attach(world, bus)` samples the live world at SAMPLE_HZ and publishes `world/debris` once the
  topic is in the contract (coord/messages.py); until then it only logs.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import deque

import mujoco
import numpy as np

log = logging.getLogger("sim.debris")

SAMPLE_HZ = 4
MOVE_EPS = 0.02        # m from the last resting place: the piece is moving
STILL_SPEED = 0.01     # m/s below this for SETTLE_S: it has settled
SETTLE_S = 1.0
FALL_DROP = 0.10       # m of height lost while moving: it fell
WINDOW_S = 3.0         # recent-motion window for stability
TILT_FULL = 30.0       # degrees of tilt that alone count as fully unstable
MOTION_FULL = 0.05     # m of motion in the window that alone counts as fully unstable
UNSTABLE = 0.5         # pile risk at or above this is reported as unstable
RES = 0.05             # perception's grid (cell = floor(coordinate / RES))
PERIOD_S = 2.0         # publish piles at least this often, events as they happen
ROBOT_GROUP = 3        # robots and what they carry (sim/scenes/backup.xml)


def _name(m, i):
    return mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i) or f"body{i}"


def debris_ids(m):
    """Free bodies that may be rubble: not mocap, not robots (geom group 3), not casualties.

    Which of them count right now is decided by `DebrisTracker.live_ids(d)`.
    """
    out = []
    for b in range(1, m.nbody):
        j = m.body_jntadr[b]
        if j < 0 or m.jnt_type[j] != mujoco.mjtJoint.mjJNT_FREE or m.body_mocapid[b] >= 0:
            continue
        geoms = range(m.body_geomadr[b], m.body_geomadr[b] + m.body_geomnum[b])
        if any(m.geom_group[g] == ROBOT_GROUP for g in geoms):
            continue
        name = _name(m, b)
        if name[:1] == "c" and name[1:2].isdigit():  # casualties c1, c2, ...
            continue
        out.append(b)
    return out


def tilt_deg(xmat):
    """Angle between world up and the body axis closest to it (0 for a box lying flat or upright)."""
    r = np.asarray(xmat).reshape(3, 3)
    return float(math.degrees(math.acos(min(1.0, float(np.max(np.abs(r[2])))))))


class _Track:
    __slots__ = ("anchor", "fell", "history", "moving", "still_since")

    def __init__(self, pos, t):
        self.anchor = pos.copy()
        self.history = deque([(t, pos.copy())])
        self.moving = False
        self.fell = False
        self.still_since = None


class DebrisTracker:
    def __init__(self, m, ids=None):
        self.m = m
        self.ids = list(debris_ids(m) if ids is None else ids)
        self.names = {b: _name(m, b) for b in self.ids}
        self.tracks: dict[int, _Track] = {}
        self.last_t = None

    def live_ids(self, d):
        """Tracked bodies that are loose rubble now: not gravity-compensated (the floor plate, a parked
        spare block) and not welded to a robot (a carried supply, a block in the gripper)."""
        held = set()
        for e in range(self.m.neq):
            if self.m.eq_type[e] == mujoco.mjtEq.mjEQ_WELD and d.eq_active[e]:
                a, b = int(self.m.eq_obj1id[e]), int(self.m.eq_obj2id[e])
                if self.m.body_mocapid[a] >= 0:
                    held.add(b)
                if self.m.body_mocapid[b] >= 0:
                    held.add(a)
        return [b for b in self.ids if self.m.body_gravcomp[b] == 0 and b not in held]

    # ---- events --------------------------------------------------------------------------
    def sample(self, d, t):
        """Record positions at time t (seconds) and return the events since the last sample."""
        events = []
        dt = None if self.last_t is None else t - self.last_t
        live = set(self.live_ids(d))
        for b in list(self.tracks):
            if b not in live:  # picked up or parked: forget it, start fresh if it comes back
                del self.tracks[b]
        for b in self.ids:
            if b not in live:
                continue
            pos = d.xpos[b].copy()
            tr = self.tracks.get(b)
            if tr is None:
                self.tracks[b] = _Track(pos, t)
                continue
            prev_t, prev = tr.history[-1]
            speed = float(np.linalg.norm(pos - prev)) / (t - prev_t) if t > prev_t else 0.0
            tr.history.append((t, pos.copy()))
            while tr.history and tr.history[0][0] < t - WINDOW_S:
                tr.history.popleft()
            name = self.names[b]
            if not tr.moving and np.linalg.norm(pos - tr.anchor) > MOVE_EPS:
                tr.moving, tr.fell, tr.still_since = True, False, None
                events.append(self._event("moved", name, pos, tr))
            if tr.moving:
                if not tr.fell and tr.anchor[2] - pos[2] > FALL_DROP:
                    tr.fell = True
                    events.append(self._event("fell", name, pos, tr))
                if dt is not None and speed < STILL_SPEED:
                    tr.still_since = t if tr.still_since is None else tr.still_since
                    if t - tr.still_since >= SETTLE_S - 1e-9:
                        events.append(self._event("settled", name, pos, tr))
                        tr.anchor, tr.moving, tr.fell, tr.still_since = pos.copy(), False, False, None
                else:
                    tr.still_since = None
        self.last_t = t
        return events

    @staticmethod
    def _event(kind, name, pos, tr):
        return {"id": name, "kind": kind, "pos": [round(float(v), 3) for v in pos],
                "moved_m": round(float(np.linalg.norm(pos - tr.anchor)), 3),
                "drop_m": round(max(0.0, float(tr.anchor[2] - pos[2])), 3)}

    def recent_motion(self, b):
        tr = self.tracks.get(b)
        if tr is None or len(tr.history) < 2:
            return 0.0
        pts = np.array([p for _, p in tr.history])
        return float(np.max(np.linalg.norm(pts - pts[-1], axis=1)))

    # ---- piles and stability -------------------------------------------------------------
    def _contacts(self, d, live):
        """(touching pairs among debris, {body: [support points below its centre]})."""
        tracked = set(live)
        pairs, support = set(), {b: [] for b in live}
        for c in d.contact[: d.ncon]:
            b1, b2 = int(self.m.geom_bodyid[c.geom[0]]), int(self.m.geom_bodyid[c.geom[1]])
            if b1 == b2:
                continue
            if b1 in tracked and b2 in tracked:
                pairs.add((min(b1, b2), max(b1, b2)))
            for b in (b1, b2):
                if b in tracked and c.pos[2] < d.xipos[b][2] - 1e-3:
                    support[b].append(c.pos.copy())
        return pairs, support

    def _overhang(self, d, b, points):
        """0 when the centre of mass sits well inside what holds it up, 1 at or past the edge (or no support).

        Per axis, the margin from the centre of mass to the edge of the support points' box, over that
        box's half-width; the worse axis counts.
        """
        if not points:
            return 1.0
        pts = np.array(points)[:, :2]
        lo, hi = pts.min(axis=0) - 0.005, pts.max(axis=0) + 0.005
        half = (hi - lo) / 2
        com = d.xipos[b][:2]
        margin = np.minimum(com - lo, hi - com)
        return float(np.clip(1.0 - np.min(margin / half), 0.0, 1.0))

    def stacks(self, d):
        """Piles of touching debris, riskiest first, each scored 0..1."""
        live = self.live_ids(d)
        pairs, support = self._contacts(d, live)
        parent = {b: b for b in live}

        def find(b):
            while parent[b] != b:
                parent[b] = parent[parent[b]]
                b = parent[b]
            return b

        for a, b in pairs:
            parent[find(a)] = find(b)
        groups: dict[int, list[int]] = {}
        for b in live:
            groups.setdefault(find(b), []).append(b)
        out = []
        for members in groups.values():
            scored = []
            for b in members:
                tilt = tilt_deg(d.xmat[b])
                over = self._overhang(d, b, support[b])
                motion = self.recent_motion(b)
                risk = 0.4 * min(1.0, tilt / TILT_FULL) + 0.35 * over + 0.25 * min(1.0, motion / MOTION_FULL)
                scored.append((risk, tilt, over, motion, b))
            risk, tilt, over, motion, worst = max(scored)
            lo, hi = self._bounds(d, members)
            out.append({
                "ids": sorted(self.names[b] for b in members),
                "risk": round(float(risk), 2),
                "worst": self.names[worst],
                "tilt_deg": round(tilt, 1),
                "overhang": round(over, 2),
                "motion_m": round(motion, 3),
                "top_z": round(float(hi[2]), 3),
                "min_xy": [round(float(v), 3) for v in lo[:2]],
                "max_xy": [round(float(v), 3) for v in hi[:2]],
                "unstable": bool(risk >= UNSTABLE),
            })
        out.sort(key=lambda s: -s["risk"])
        return out

    def _bounds(self, d, members):
        """World-aligned bounding box (min corner, max corner) of a pile's geoms."""
        lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
        for b in members:
            for g in range(self.m.body_geomadr[b], self.m.body_geomadr[b] + self.m.body_geomnum[b]):
                r = d.geom_xmat[g].reshape(3, 3)
                half = np.abs(r) @ self.m.geom_size[g] if self.m.geom_type[g] == mujoco.mjtGeom.mjGEOM_BOX \
                    else np.full(3, self.m.geom_rbound[g])
                lo = np.minimum(lo, d.geom_xpos[g] - half)
                hi = np.maximum(hi, d.geom_xpos[g] + half)
        return lo, hi

    # ---- outputs -------------------------------------------------------------------------
    def risk_cells(self, d, stacks=None, res=RES):
        """Secondary-fall risk: grid columns an unstable pile could land on if it toppled.

        A pile can fall about its own height in any direction, so its footprint is grown by top_z.
        Shaped like map/hazards entries, for scoring perception's own estimate against.
        """
        stacks = self.stacks(d) if stacks is None else stacks
        cells = {}
        for s in stacks:
            if not s["unstable"]:
                continue
            reach = s["top_z"]
            i0, j0 = (math.floor((v - reach) / res) for v in s["min_xy"])
            i1, j1 = (math.floor((v + reach) / res) for v in s["max_xy"])
            why = (f"pile {'+'.join(s['ids'][:4])}{'...' if len(s['ids']) > 4 else ''} risk {s['risk']:.2f}: "
                   f"tilt {s['tilt_deg']:.0f} deg, overhang {s['overhang']:.2f}, moved {s['motion_m'] * 100:.0f} cm")
            for i in range(i0, i1 + 1):
                for j in range(j0, j1 + 1):
                    cells.setdefault((i, j), {"cell": [i, j, 0], "status": "at_risk", "why": why, "estimate": True})
        return list(cells.values())

    def message(self, d, t, events):
        """The world/debris payload (sim truth, marked as such)."""
        return {"t": round(float(t), 2), "truth": True, "events": events, "stacks": self.stacks(d)}


def _contract_topics():
    try:
        from coord import messages
    except ImportError:  # the sim lane's own tests run without pydantic
        return set()
    return set(messages.TOPICS)


def attach(world, bus, rate_hz=SAMPLE_HZ, topics=None):
    """Sample the live world and publish world/debris (events at once, piles every PERIOD_S).

    `topics` is the set of contract topics (default: coord/messages.py TOPICS).
    """
    tracker = DebrisTracker(world.m)
    world.debris = tracker
    publish = "world/debris" in (_contract_topics() if topics is None else topics)

    async def loop():
        last = -math.inf
        while True:
            events = tracker.sample(world.d, world.t)
            if events or world.t - last >= PERIOD_S:
                last = world.t
                msg = tracker.message(world.d, world.t, events)
                if publish:
                    try:
                        await bus.publish("world/debris", msg)
                    except Exception:
                        log.exception("publish world/debris failed")
                elif events:
                    log.info("debris: %s", ", ".join(f"{e['id']} {e['kind']}" for e in events))
            await asyncio.sleep(1.0 / rate_hz)

    world.debris_task = asyncio.get_running_loop().create_task(loop())
    return tracker
