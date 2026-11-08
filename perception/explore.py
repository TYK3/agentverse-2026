"""Scout exploration: head for the nearest frontier, obey re-looks first, re-scan after a change (T09, Z1).

The map is one LiDAR layer thick, so frontiers and paths live in the Scout's layer k and use the four
in-layer neighbours (the layers above and below are always unknown).

Only the Scout's own scans steer it (Z1): a frontier counts only inside the building as the LiDAR saw
it (measured walls within ENCLOSED_M in at least 3 of the 4 grid directions), and after a shake it re-visits the cells it had predicted at_risk, then any
cell the scan diff saw change, getting within LOOK of each so the LiDAR measures it again.
"""

import math
import re
from collections import deque

from perception.grid import GROUND, RES, cell_of

CLEAR = 2             # a Scout path keeps this many cells (0.1 m) from anything occupied, measured
                      # as a radius: a square would also count its corners (0.14 m away) and close the
                      # 0.32 m diagonal between wall b3 and rubble b12 just inside the breach
MIN_UNKNOWN = 3       # a frontier needs this many unknown cells in its 5x5 window (skips specks)
CARROT = 12           # scout/goto targets at most this many path cells ahead (0.6 m)
REACHED = 0.15        # metres: a target this close counts as reached
STALL = 5             # decisions without getting 5 cm closer before a frontier is given up
HOLD = 20.0           # seconds a re-look or a planner scout/goto keeps priority at most
ENCLOSED_M = 4.0      # metres a frontier looks along each grid axis for a measured wall
LOOK = 1.0            # metres: close enough to a re-scan target for the LiDAR to measure it again
VISIT_HOLD = 15.0     # seconds one re-scan visit may take before the next
AHEAD = 0.18          # metres sim keeps clear ahead before it moves (CLEARANCE 0.15 + one 0.03 m step)
HALF_WIDTH = 0.08     # Scout chassis half width; with AHEAD this mirrors sim/world.py's _free_ahead
ZONE = "re-scan keep-out zone"   # reason prefix of a visit that stays in view until the zone lifts

SIDES = ((1, 0), (-1, 0), (0, 1), (0, -1))
DISK = tuple((di, dj) for di in range(-CLEAR, CLEAR + 1) for dj in range(-CLEAR, CLEAR + 1)
             if di * di + dj * dj <= CLEAR * CLEAR)
AROUND = tuple((di, dj) for di in (-1, 0, 1) for dj in (-1, 0, 1) if di or dj)
_CELL = re.compile(r"\[\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\]")


def centre(c, z):
    return [round((c[0] + 0.5) * RES, 3), round((c[1] + 0.5) * RES, 3), z]


class Explorer:
    def __init__(self, grid):
        self.grid = grid
        self.pose = None          # Scout position from sensors/scout
        self.bad = set()          # (i, j) of at_risk or collapsed hazard cells
        self.zone = set()         # (i, j) of keep-out (exclusion) cells in the last map/hazards
        self.hold = None          # (target, until, reason, radius) of a re-look, visit or planner scout/goto
        self.visits = []          # [(cell, reason)] still to re-scan after a change, nearest first
        self.visited = set()      # re-scan cells already queued since the last change
        self.target = None        # frontier cell we are heading for
        self.given_up = set()     # frontiers reached, or not reachable, that stayed frontiers
        self.progress = (None, math.inf, 0)   # (target, closest so far, decisions since closer)
        self.sent = None          # our last scout/goto, to tell it from the planner's
        self.blocked = False      # sim refused to drive toward our last scout/goto

    # ---- bus callbacks ----------------------------------------------------------

    def on_sensors(self, data):
        self.pose = data["pose"]["pos"]
        self.blocked = data.get("motion", {}).get("state") == "blocked"

    def _enclosed(self, i, j):
        """True if measured occupied cells lie within ENCLOSED_M along at least 3 of +x, -x, +y, -y.

        Inside a room walls surround a cell; outside the building at least two directions open onto
        nothing (LiDAR misses leave no cells), so frontiers there are skipped.
        """
        k, n, walls = self._k(), int(ENCLOSED_M / RES), 0
        for di, dj in SIDES:
            for s in range(1, n + 1):
                cur = self.grid.cells.get((i + di * s, j + dj * s, k))
                if cur and cur["state"] == "seen" and cur["occupied"]:
                    walls += 1
                    break
        return walls >= 3

    def on_hazards(self, data):
        self.bad = {(h["cell"][0], h["cell"][1]) for h in data if h["status"] in ("at_risk", "collapsed")}
        zone = {(h["cell"][0], h["cell"][1]) for h in data if h.get("exclusion")}
        new = zone - self.zone
        self.zone = zone
        if new:
            # A keep-out zone lifts only after fresh scans of the moved voxels (perception/motion.py), so go
            # back and look, even where a re-scan visit already passed: nobody else will.
            self.visited -= {v for v in self.visited if any(math.dist(v, c) * RES < LOOK / 2 for c in new)}
            self._queue(new, f"{ZONE} until it settles: cell")

    def on_goto(self, data, t):
        if data is not self.sent:
            self.hold = (data["target"], t + HOLD, None, REACHED)

    def on_decision(self, data, t):
        m = _CELL.search(data.get("reason", ""))
        if data.get("outcome") == "relook" and m:
            cell = tuple(int(v) for v in m.groups())
            self.hold = (cell, t + HOLD, f"re-look at cell {list(cell)} (planner: {data['reason']})", REACHED)

    def on_change(self, data):
        """A shake was felt (or a block injected): re-scan every cell predicted at_risk, nearest first.

        Which blocks moved (moved_blocks) is sim truth and is not read; the scan diff finds them.
        """
        kind = "aftershock" if data.get("kind", "aftershock") == "aftershock" else "injected block"
        self.visits, self.visited = [], set()
        self._queue(self.bad, f"re-scan after the {kind}: predicted at-risk cell")
        self.target = None

    def on_diff(self, cells):
        """The scan diff saw cells change: go and look at them closer."""
        self._queue({(c[0], c[1]) for c in cells}, "re-scan where the scan changed: cell")

    def _queue(self, cells, reason):
        """Queue one visit per LOOK-sized patch of `cells`, nearest the Scout first."""
        for ij in sorted(cells):
            if any(math.dist(ij, v) * RES < LOOK / 2 for v in self.visited):
                continue
            self.visited.add(ij)
            self.visits.append(((*ij, GROUND), f"{reason} {[ij[0], ij[1], GROUND]}"))
        if self.pose is not None:
            here = cell_of(self.pose)[:2]
            self.visits.sort(key=lambda v: math.dist(v[0][:2], here))

    # ---- one decision a second --------------------------------------------------

    def tick(self, t):
        """The scout/goto to publish now, or None (nothing to do, or a hold is in force)."""
        if self.pose is None:
            return None
        self.visits = [v for v in self.visits if not v[1].startswith(ZONE) or v[0][:2] in self.zone]
        if self.hold is None and self.visits:
            cell, reason = self.visits.pop(0)
            self.hold = (cell, t + VISIT_HOLD, reason, LOOK)
        if self.hold:
            target, until, reason, radius = self.hold
            here = centre(target, self.pose[2]) if isinstance(target, tuple) else target
            near = math.dist(here[:2], self.pose[:2]) < radius
            if reason and reason.startswith(ZONE) and t <= until and tuple(target[:2]) in self.zone:
                if near:
                    return None                   # stay in view of the zone until fresh scans lift it
                return self._goto(target, reason)
            if t > until or near:
                self.hold = None
                if self.visits:
                    return self.tick(t)
            elif reason is None:
                return None                       # the planner's own scout/goto is driving the Scout
            else:
                return self._goto(target, reason)

        if self.target:
            gap = math.dist(centre(self.target, 0)[:2], self.pose[:2])
            target, best, stuck = self.progress
            if target != self.target or gap < best - 0.05:
                self.progress = (self.target, gap, 0)
            else:
                self.progress = (target, best, stuck + 1)
            if gap < REACHED or self.progress[2] >= STALL or self.blocked:
                self.given_up.add(self.target)
        found = self._nearest_frontier()
        if found is None:
            self.target = None
            return None
        self.target, unknown, path = found
        return self._send(path, f"frontier at cell {self._plan(self.target)}, {unknown} unknown neighbours")

    # ---- map helpers ------------------------------------------------------------

    @staticmethod
    def _plan(cell):
        """A cell as the planner and console name it: map/cells is flat, every cell is k = 0."""
        return [cell[0], cell[1], GROUND]

    def _k(self):
        return cell_of(self.pose)[2]

    def _free(self, i, j):
        cur = self.grid.cells.get((i, j, self._k()))
        return bool(cur and cur["state"] == "seen" and not cur["occupied"])

    def _passable(self, i, j):
        if (i, j) in self.bad or not self._free(i, j):
            return False
        k = self._k()
        for di, dj in DISK:
            cur = self.grid.cells.get((i + di, j + dj, k))
            if cur and cur["occupied"]:
                return False
        return True

    def _unknown_near(self, i, j):
        k = self._k()
        return sum((i + di, j + dj, k) not in self.grid.cells for di in range(-2, 3) for dj in range(-2, 3))

    def _is_frontier(self, i, j):
        k = self._k()
        if not any((i + di, j + dj, k) not in self.grid.cells for di, dj in SIDES):
            return False
        return self._unknown_near(i, j) >= MIN_UNKNOWN and self._enclosed(i, j)

    def _bfs(self):
        """Parents of every passable cell reachable from the Scout, nearest first, in order."""
        si, sj, _ = cell_of(self.pose)
        start = [(si + di, sj + dj) for di in range(-3, 4) for dj in range(-3, 4) if self._passable(si + di, sj + dj)]
        parent = {c: None for c in start}
        queue, order = deque(start), []
        while queue:
            c = queue.popleft()
            order.append(c)
            for di, dj in AROUND:
                n = (c[0] + di, c[1] + dj)
                if n not in parent and self._passable(*n):
                    parent[n] = c
                    queue.append(n)
        return parent, order

    def _nearest_frontier(self):
        parent, order = self._bfs()
        k = self._k()
        for c in order:
            if (*c, k) not in self.given_up and self._is_frontier(*c):
                return (*c, k), self._unknown_near(*c), self._path(parent, c)
        return None

    def _path(self, parent, c):
        path = []
        while c is not None:
            path.append(c)
            c = parent[c]
        return path[::-1]

    def _goto(self, cell, reason):
        """Path toward the passable cell nearest a re-look cell."""
        parent, order = self._bfs()
        if not order:
            return None
        best = min(order, key=lambda c: math.dist(c, cell[:2]))
        return self._send(self._path(parent, best), reason)

    def _send(self, path, reason):
        """scout/goto to the farthest path cell, at most CARROT ahead, the Scout can drive to straight."""
        z = self.pose[2]
        pick = path[0]
        for c in path[1:CARROT + 1]:
            if not (self._straight(centre(c, z)) and self._clear_ahead(centre(c, z))):
                break
            pick = c
        self.sent = {"target": centre(pick, z), "reason": reason}
        return self.sent

    def _straight(self, goal):
        x, y = self.pose[:2]
        n = max(1, int(math.dist((x, y), goal[:2]) / (RES / 2)))
        for s in range(n + 1):
            p = (x + (goal[0] - x) * s / n, y + (goal[1] - y) * s / n, self.pose[2])
            i, j, _ = cell_of(p)
            if (i, j) in self.bad or not self._free(i, j):
                return False      # the straight line may not cut through an at_risk or collapsed cell
        return True

    def _clear_ahead(self, goal):
        """True if sim would drive all the way to goal: no occupied cell in the strip HALF_WIDTH either
        side of the line from the Scout to AHEAD past goal (sim stops when its forward rays hit one)."""
        x, y = self.pose[:2]
        length = math.dist((x, y), goal[:2])
        if length < 1e-6:
            return True
        fx, fy = (goal[0] - x) / length, (goal[1] - y) / length
        k = self._k()
        step = RES / 2
        for s in range(int((length + AHEAD) / step) + 1):
            for w in range(-2, 3):
                off = HALF_WIDTH * w / 2
                p = (x + fx * s * step - fy * off, y + fy * s * step + fx * off, 0)
                cur = self.grid.cells.get((*cell_of(p)[:2], k))
                if cur and cur["occupied"]:
                    return False
        return True
