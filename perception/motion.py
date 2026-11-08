"""Sensed debris motion and keep-out zones (L5): a precaution from what the Scout saw move, not a prediction.

Every LiDAR ray (the 0.075 m plane) and every depth ray (sensors/scout.points from points_from) feeds a
0.05 m voxel watch. Each frame gives a voxel one observation: occupied if any ray returned from it (a
return beats a pass, as in the grid: neighbouring rays of one sweep often split a surface voxel), else
free if a ray passed through it, continuing at least MARGIN beyond. States are kept per viewpoint
(the sensor's origin binned to VIEW metres): from a new viewpoint a surface corner can look free that
looked occupied before, which is aliasing, not motion. Motion is a change seen from the same place,
so the Scout senses it while it watches a pile (a pause, a re-look). A voxel's state is established
once SETTLED frames from one viewpoint agree. Then:

  vanished  an established occupied voxel observed free in VANISH_FRAMES frames running;
  appeared  an established free voxel observed occupied in APPEAR_FRAMES frames running, not touching
            anything already occupied (a return landing one voxel off a surface is not motion).

MIN_MOVED such events within CLUSTER of each other open a zone: every plan column within EXCLUDE of
them is a keep-out zone (map/hazards `exclusion: true`; routes never pass). A zone is lifted only by
fresh observation: QUIET_FRAMES frames that each re-measure at least QUIET_RAYS voxels in its moved
columns with no new motion there. Time alone never lifts it.

No world/change, block pose or sim truth is read: a shake is not needed to see something slide.
"""

import math

VOX = 0.05
SETTLED = 5           # agreeing frames that establish a voxel as free or occupied
APPEAR_FRAMES = 2
VANISH_FRAMES = 3
MARGIN = 0.15         # metres a ray must continue past a voxel for its pass to count
VIEW = 0.1            # metres: sensor origins this close share a viewpoint
INTO = 0.01           # metres past a return it is binned: a surface on a voxel boundary lands inside it
MIN_MOVED = 3         # motion events that open a zone
CLUSTER = 0.3         # metres: events this close belong to one zone
EXCLUDE = 0.5         # metres around moved columns that are kept out
QUIET_FRAMES = 6      # frames re-measuring the moved voxels with no motion before a zone lifts
QUIET_RAYS = 3        # voxels in the moved columns a frame must re-measure to count toward lifting
CAM_FWD, CAM_Z = 0.15, 0.18   # Scout depth camera mount (docs/hardware.md), when points_from is absent
DEPTH_CARVE = 512     # depth rays walked for free space per frame (every point still counts as a hit)
FACES = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


def voxel(p):
    return tuple(math.floor(v / VOX) for v in p)


class Zone:
    def __init__(self, events, t):
        self.voxels = {v for v, _, _ in events}
        self.opened = t
        self.last = t
        self.quiet = 0
        self.kinds = {k for _, _, k in events}

    def columns(self):
        return {(v[0], v[1]) for v in self.voxels}

    def heights(self):
        zs = [(v[2] + 0.5) * VOX for v in self.voxels]
        return min(zs), max(zs)


class MotionWatch:
    def __init__(self):
        self.v = {}            # (voxel, viewpoint) -> [state "free"|"occ", agreeing frames, contrary frames since]
        self.view = None       # the viewpoint of the rays being added
        self.events = []       # (voxel, t, "vanished"|"appeared") not yet in a zone
        self.zones = []
        self.lifted = []       # zones lifted by fresh observation, for the reasons
        self.seen = set()      # voxels measured in the current frame
        self.obs = {}          # voxel -> True (a return) or False (only passes) in the current frame
        self.t = 0.0

    # ---- rays ------------------------------------------------------------------------------

    def ray(self, origin, end, hit=True):
        """One ray from `origin` to `end`: passes along it (MARGIN short of the end), a hit at the end."""
        self.view = ("ray", *(math.floor(o / VIEW) for o in origin))
        length = math.dist(origin, end)
        if length < 1e-6:
            return
        n = int((length - MARGIN) / VOX)
        last = None
        for s in range(n + 1):
            f = s * VOX / length
            v = voxel([o + (e - o) * f for o, e in zip(origin, end)])
            if v != last:
                self.obs.setdefault((v, self.view), False)
                last = v
        if hit:
            f = 1 + INTO / length
            self.obs[(voxel([o + (e - o) * f for o, e in zip(origin, end)]), self.view)] = True

    def add_sensors(self, data, lidar_max=6.0):
        """Feed one sensors/scout frame (LiDAR always, depth points when present); then update zones."""
        self.t = data.get("t", self.t)
        self.obs = {}
        pos, yaw = data["pose"]["pos"], data["pose"].get("yaw", 0.0)
        ranges = data.get("lidar") or []
        for k, r in enumerate(ranges):
            if r >= lidar_max:
                continue                                   # no return is no measurement
            a = 2 * math.pi * k / len(ranges)
            self.ray(pos, [pos[0] + r * math.cos(a), pos[1] + r * math.sin(a), pos[2]])
        points = data.get("points")
        if points:
            cam = data.get("points_from") or [pos[0] + CAM_FWD * math.cos(yaw), pos[1] + CAM_FWD * math.sin(yaw), CAM_Z]
            step = max(1, len(points) // DEPTH_CARVE)
            for i, p in enumerate(points):
                if i % step == 0:
                    self.ray(cam, p)
                else:
                    self.obs[(voxel(p), self.view)] = True
        for key, hit in self.obs.items():
            (self._hit if hit else self._pass)(key)
        self.seen = {v for v, _ in self.obs}
        self._frame()

    # ---- voxel states ----------------------------------------------------------------------

    def _pass(self, key):
        v = key[0]
        s = self.v.get(key)
        if s is None:
            self.v[key] = ["free", 1, 0]
        elif s[0] == "free":
            s[1], s[2] = s[1] + 1, 0
        else:
            s[2] += 1
            if s[2] >= VANISH_FRAMES:
                if s[1] >= SETTLED:
                    self.events.append((v, self.t, "vanished"))
                s[:] = ["free", 1, 0]

    def _hit(self, key):
        v, view = key
        s = self.v.get(key)
        if s is None:
            self.v[key] = ["occ", 1, 0]
        elif s[0] == "occ":
            s[1], s[2] = s[1] + 1, 0
        else:
            s[2] += 1
            if s[2] >= APPEAR_FRAMES:
                if s[1] >= SETTLED and not self._touches_occupied(v, view):
                    self.events.append((v, self.t, "appeared"))
                s[:] = ["occ", 1, 0]

    def _touches_occupied(self, v, view):
        for f in FACES:
            s = self.v.get(((v[0] + f[0], v[1] + f[1], v[2] + f[2]), view))
            if s and s[0] == "occ" and s[1] >= SETTLED:
                return True
        return False

    # ---- zones -----------------------------------------------------------------------------

    def _frame(self):
        """Merge this frame's motion into zones, open new ones, and count quiet re-scans toward lifting."""
        recent = {}
        for v, t, kind in self.events:              # one entry per voxel (several viewpoints may see it)
            if self.t - t <= 2.0:
                recent.setdefault(v, (t, kind))
        self.events = []
        moved = set()
        for v, (t, kind) in list(recent.items()):
            zone = next((z for z in self.zones if self._near(v, z.voxels)), None)
            if zone is not None:
                zone.voxels.add(v)
                zone.kinds.add(kind)
                zone.last, zone.quiet = max(zone.last, t), 0
                moved.add(id(zone))
                del recent[v]
        while True:
            group = self._cluster(recent)
            if not group:
                break
            zone = Zone([(v, *recent[v]) for v in group], self.t)
            self.zones.append(zone)
            moved.add(id(zone))
            for v in group:
                del recent[v]
        self.events = [(v, t, kind) for v, (t, kind) in recent.items()]     # strays wait up to 2 s
        seen_columns = {}
        for v in self.seen:
            seen_columns[(v[0], v[1])] = seen_columns.get((v[0], v[1]), 0) + 1
        for zone in self.zones:
            if id(zone) not in moved and sum(seen_columns.get(c, 0) for c in zone.columns()) >= QUIET_RAYS:
                zone.quiet += 1
        for zone in [z for z in self.zones if z.quiet >= QUIET_FRAMES]:
            self.zones.remove(zone)
            self.lifted.append(zone)

    def _near(self, v, voxels):
        return any(math.dist(v, o) * VOX <= CLUSTER for o in voxels)

    def _cluster(self, recent):
        for v in recent:
            group = [o for o in recent if math.dist(v, o) * VOX <= CLUSTER]
            if len(group) >= MIN_MOVED:
                return group
        return None

    def keep_out(self):
        """{(i, j): why} for every plan column in a zone (EXCLUDE around the voxels that moved)."""
        out = {}
        r = int(EXCLUDE / VOX)
        for zone in self.zones:
            lo, hi = zone.heights()
            kinds = " and ".join(sorted("moved away" if k == "vanished" else "landed" for k in zone.kinds))
            why = (f"exclusion zone: debris {kinds} {lo:.2f}-{hi:.2f} m up, sensed at {zone.opened:.1f} s "
                   f"(last at {zone.last:.1f} s); a precaution from observed motion, lifted after "
                   f"{QUIET_FRAMES} quiet re-scans ({zone.quiet} so far)")
            for i, j in zone.columns():
                for di in range(-r, r + 1):
                    for dj in range(-r, r + 1):
                        if di * di + dj * dj <= r * r:
                            out.setdefault((i + di, j + dj), why)
        return out
