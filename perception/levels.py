"""L4 multi-level map: cells keep their real height, so B1, ground and L1 do not collapse into one plan.

A cell is `[i, j, k]` with i, j = floor(x / RES), floor(y / RES) as in grid.py, and k = round(floor height
/ RES): the height of the floor a robot would stand on, in RES steps. Ground stays k = 0 (what the T12
planner routes on); L1 at +0.6 m is k = 12, B1 at -0.6 m is k = -12, ramp cells lie in between. The same
(i, j) can hold several cells, one per level.

Only what was measured counts (no seen cell is a guess):
  - the trail: the cells under the Scout's footprint, at the floor height it measured standing there
    (pose z minus RIDE). This is the only way a ramp gets into the map, and it overrides anything the
    LiDAR said about that column within HEADROOM, since LiDAR rays over a ramp mouth float above the
    real (lower) floor.
  - LiDAR at the Scout's own floor height k: free cells within FREE_RANGE and hits at any range.
    On flat floor (its recent travel rose less than FLAT per metre, and every trail cell within NEAR
    is at its level) every ray counts. Near a ramp only the rays within ACROSS of square to the
    uphill direction (a plane fitted to the trail heights there) count: they stay level with the
    ramp surface and map its rails and side walls; the rest would hit the ramp itself. A 2D LiDAR cannot see a drop, so free range is kept short and the scene rails its drops.
  - a refused step: if the Scout reports `blocked` short of its target, the cells just ahead are
    marked occupied at its level (a drop, kerb or wall it would not drive into).
GridLevels.message() is a map/cells payload (contract shape). It is not wired into perception.start:
the hub's map/cells is still grid.py's flat k = 0 map; this one is for multi-level runs (sim.levels).
"""

import math

from perception.grid import cell_of

RES = 0.05
RIDE = 0.075          # pose z is the sensor origin, this far above the floor (sim/scenes/*.xml)
HALF_WIDTH = 0.08     # Scout footprint half width: the trail covers the cells under it
FREE_RANGE = 1.5      # metres: LiDAR free space is believed this far; hits at any range
MAX_RANGE = 6.0
FLAT = 0.05           # rise per metre below which the Scout is on flat floor and may scan
SLOPE_BASE = 0.10     # metres of travel the slope estimate looks back over
ACROSS = math.radians(20)  # on a ramp, rays this close to square to the slope still map
NEAR = 0.25           # metres of trail around the Scout used to find a ramp and its slope
HEADROOM = 8          # k steps (0.4 m): a trail cell clears LiDAR free cells this far above or below it


def k_of(floor_z, res=RES):
    return round(floor_z / res)


class GridLevels:
    def __init__(self, res=RES):
        self.res = res
        self.cells = {}            # (i, j, k) -> {"state", "occupied", "source"}
        self.trail = {}            # (i, j) -> k measured under the Scout
        self.poses = []            # (x, y, floor_z) history for the slope estimate
        self.changed = set()

    # ---- writing ----------------------------------------------------------------
    def _set(self, c, occupied, source):
        cur = self.cells.get(c)
        if cur and cur["source"] == "trail" and source != "trail":
            return                 # what the Scout stood on beats anything else
        if cur and cur["occupied"] and not occupied and source == "lidar":
            return                 # a return beats a pass, as in grid.py
        new = {"state": "seen", "occupied": occupied, "source": source}
        if cur != new:
            self.cells[c] = new
            self.changed.add(c)

    def _drop(self, c):
        if self.cells.pop(c, None) is not None:
            self.changed.add(c)

    def _trail_cell(self, i, j, k):
        self.trail[(i, j)] = k
        for dk in range(-HEADROOM, HEADROOM + 1):
            other = (i, j, k + dk)
            cur = self.cells.get(other)
            if dk and cur and cur["source"] == "lidar" and not cur["occupied"]:
                self._drop(other)          # air the LiDAR took for floor
        self._set((i, j, k), False, "trail")

    def slope(self):
        """(rise per metre, direction of travel in radians) over the last SLOPE_BASE metres driven.

        (0, None) before the Scout has moved; (1, None) if it has moved less than SLOPE_BASE in total.
        """
        if len(self.poses) < 2:
            return 0.0, None
        x, y, z = self.poses[-1]
        for px, py, pz in reversed(self.poses[:-1]):
            run = math.hypot(x - px, y - py)
            if run >= SLOPE_BASE:
                return abs(z - pz) / run, math.atan2(y - py, x - px)
        moved = math.hypot(x - self.poses[0][0], y - self.poses[0][1])
        return (0.0 if moved < 1e-3 else 1.0), None

    def add_sensors(self, data):
        """One sensors/scout payload: pose, LiDAR and motion."""
        x, y, z = data["pose"]["pos"]
        floor = z - RIDE
        k = k_of(floor, self.res)
        if not self.poses or self.poses[-1][:2] != (x, y):
            self.poses.append((x, y, floor))
            self.poses = self.poses[-200:]
        r = math.ceil(HALF_WIDTH / self.res)
        ci, cj, _ = cell_of((x, y, 0.0), self.res)
        for di in range(-r, r + 1):
            for dj in range(-r, r + 1):
                cx, cy = (ci + di + 0.5) * self.res, (cj + dj + 0.5) * self.res
                if math.hypot(cx - x, cy - y) <= HALF_WIDTH:
                    self._trail_cell(ci + di, cj + dj, k)
        rise, _ = self.slope()
        up = self._uphill(ci, cj, k)
        flat = rise < FLAT and up is None
        if flat or up is not None:
            self._scan((x, y), k, data["lidar"], None if flat else up)
        motion = data.get("motion") or {}
        if motion.get("state") == "blocked" and motion.get("target"):
            self._blocked((x, y), k, motion["target"])
        return flat

    def _uphill(self, ci, cj, k):
        """Direction (radians) the floor rises in around column (ci, cj), fitted to the trail within NEAR,
        or None if every trail cell there is at level k (flat floor, as far as the Scout has stood)."""
        r = math.ceil(NEAR / self.res)
        pts = [(di, dj, self.trail[(ci + di, cj + dj)] - k)
               for di in range(-r, r + 1) for dj in range(-r, r + 1) if (ci + di, cj + dj) in self.trail]
        if not any(dk for _, _, dk in pts):
            return None
        # least-squares plane dk = a*di + b*dj + c, centred so a and b separate from c
        n = len(pts)
        mi, mj, mk = (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n, sum(p[2] for p in pts) / n)
        sii = sum((p[0] - mi) ** 2 for p in pts)
        sjj = sum((p[1] - mj) ** 2 for p in pts)
        sij = sum((p[0] - mi) * (p[1] - mj) for p in pts)
        sik = sum((p[0] - mi) * (p[2] - mk) for p in pts)
        sjk = sum((p[1] - mj) * (p[2] - mk) for p in pts)
        det = sii * sjj - sij * sij
        if abs(det) < 1e-9:
            return 0.0 if sii > sjj else math.pi / 2     # a line of trail: take it as the slope's line
        a = (sik * sjj - sjk * sij) / det
        b = (sjk * sii - sik * sij) / det
        return math.atan2(b, a)

    def _scan(self, xy, k, ranges, along=None):
        """Map one sweep at level k; with `along` (a ramp's uphill direction) only rays square to it."""
        x, y = xy
        n = len(ranges)
        for idx, rng in enumerate(ranges):
            a = 2 * math.pi * idx / n
            if along is not None and abs(math.sin(a - along)) < math.cos(ACROSS):
                continue
            dx, dy = math.cos(a), math.sin(a)
            s = 0.0
            while s < min(rng, FREE_RANGE):
                i, j, _ = cell_of((x + s * dx, y + s * dy, 0.0), self.res)
                if self._trail_k(i, j, k) is None:
                    self._set((i, j, k), False, "lidar")
                s += self.res
            if rng < MAX_RANGE:
                i, j, _ = cell_of((x + rng * dx, y + rng * dy, 0.0), self.res)
                self._set((i, j, k), True, "lidar")

    def _trail_k(self, i, j, k):
        """The trail's k for column (i, j) if it differs from k within HEADROOM, else None."""
        tk = self.trail.get((i, j))
        return tk if tk is not None and tk != k and abs(tk - k) <= HEADROOM else None

    def _blocked(self, xy, k, target):
        """The Scout refused a step toward target (a drop, a kerb or a wall too close): the cells just
        ahead are occupied at its level. The refusal is itself the measurement, whatever the LiDAR saw."""
        x, y = xy
        if math.hypot(target[0] - x, target[1] - y) < 0.05:
            return                 # over the target on the wrong level: nothing ahead was refused
        heading = math.atan2(target[1] - y, target[0] - x)
        for s in (0.1, 0.15):
            i, j, _ = cell_of((x + s * math.cos(heading), y + s * math.sin(heading), 0.0), self.res)
            self.cells[(i, j, k)] = {"state": "seen", "occupied": True, "source": "refused"}
            self.changed.add((i, j, k))

    def refuse(self, c):
        """Cell c is not drivable: the Scout tried to step into it and the sim refused the move."""
        c = tuple(c)
        self.cells[c] = {"state": "seen", "occupied": True, "source": "refused"}
        self.changed.add(c)

    # ---- reading ----------------------------------------------------------------
    def message(self, t, everything=False):
        """map/cells (contract shape); every cell, or only those changed since the last message.

        A delta lists a cell the trail cleared as unknown, so a consumer drops it too.
        """
        keys = self.cells if everything else self.changed
        cells = []
        for c in sorted(keys):
            cur = self.cells.get(c)
            cells.append({"cell": list(c), "state": cur["state"] if cur else "unknown",
                          "occupied": cur["occupied"] if cur else False})
        self.changed = set()
        return {"t": round(t, 2), "res": self.res, "cells": cells}

    def levels(self):
        """Sorted distinct k values that hold a trail cell (the floors the Scout has stood on)."""
        return sorted(set(self.trail.values()))
