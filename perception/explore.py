"""Scout exploration: head for the nearest frontier, obey re-looks first, re-scan after a change (T09).

The map is one LiDAR layer thick, so frontiers and paths live in the Scout's layer k and use the four
in-layer neighbours (the layers above and below are always unknown).
"""

import math
import re
from collections import deque

from perception.grid import RES, cell_of

CLEAR = 2             # a Scout path keeps this many cells (0.1 m) from anything occupied, measured
                      # as a radius: a square would also count its corners (0.14 m away) and close the
                      # 0.32 m diagonal between wall b3 and rubble b12 just inside the breach
MIN_UNKNOWN = 3       # a frontier needs this many unknown cells in its 5x5 window (skips specks)
CARROT = 12           # scout/goto targets at most this many path cells ahead (0.6 m)
REACHED = 0.15        # metres: a target this close counts as reached
STALL = 5             # decisions without getting 5 cm closer before a frontier is given up
HOLD = 20.0           # seconds a re-look or a planner scout/goto keeps priority at most
RESCAN = 0.5          # metres around a moved block that become unknown again
AHEAD = 0.18          # metres sim keeps clear ahead before it moves (CLEARANCE 0.15 + one 0.03 m step)
HALF_WIDTH = 0.08     # Scout chassis half width; with AHEAD this mirrors sim/world.py's _free_ahead
NEW_BLOCK = (0.1, 0.1, 0.08)   # half-extents assumed for a block_added block (sim's spare rubble x1)

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
        self.blocks = {}          # block id -> (pos, size) from scene/loaded
        self.bounds = None        # (lo, hi) cells of the building's walls: frontiers stay inside
        self.bad = set()          # (i, j) of at_risk or collapsed hazard cells
        self.hold = None          # (target, until, reason) of a re-look or a planner scout/goto
        self.rescan = set()       # cells made unknown by the last world/change
        self.change = ""          # what the last world/change did, for the reason string
        self.target = None        # frontier cell we are heading for
        self.given_up = set()     # frontiers reached, or not reachable, that stayed frontiers
        self.progress = (None, math.inf, 0)   # (target, closest so far, decisions since closer)
        self.sent = None          # our last scout/goto, to tell it from the planner's
        self.blocked = False      # sim refused to drive toward our last scout/goto

    # ---- bus callbacks ----------------------------------------------------------

    def on_sensors(self, data):
        self.pose = data["pose"]["pos"]
        self.blocked = data.get("motion", {}).get("state") == "blocked"

    def on_scene(self, data):
        """Remember the blocks, and explore only inside the walls (outside, misses leave it all unknown)."""
        self.blocks = {b["id"]: (b["pos"], b["size"]) for b in data["blocks"]}
        walls = [b for b in data["blocks"] if b.get("label") == "wall"]
        if walls:
            lo = cell_of([min(b["pos"][a] - b["size"][a] for b in walls) for a in (0, 1)] + [0])
            hi = cell_of([max(b["pos"][a] + b["size"][a] for b in walls) for a in (0, 1)] + [0])
            self.bounds = (lo, hi)

    def on_hazards(self, data):
        self.bad = {(h["cell"][0], h["cell"][1]) for h in data if h["status"] in ("at_risk", "collapsed")}

    def on_goto(self, data, t):
        if data is not self.sent:
            self.hold = (data["target"], t + HOLD, None)

    def on_decision(self, data, t):
        m = _CELL.search(data.get("reason", ""))
        if data.get("outcome") == "relook" and m:
            cell = tuple(int(v) for v in m.groups())
            self.hold = (cell, t + HOLD, f"re-look at cell {list(cell)} (planner: {data['reason']})")

    def on_change(self, data):
        """Every cell within 0.5 m of a moved block becomes unknown, so the Scout re-scans it.

        A block_added change names a block scene/loaded never listed; with an optional "pos" it is
        placed there (a NEW_BLOCK box), without one it is left for the LiDAR to find.
        """
        forget = set()
        for b in data.get("moved_blocks", []):
            if b not in self.blocks and data.get("pos"):
                self.blocks[b] = (data["pos"], NEW_BLOCK)
            if b not in self.blocks:
                continue
            pos, size = self.blocks[b]
            lo = cell_of([p - s - RESCAN for p, s in zip(pos[:2], size[:2])] + [0])
            hi = cell_of([p + s + RESCAN for p, s in zip(pos[:2], size[:2])] + [0])
            forget |= {c for c in self.grid.cells if lo[0] <= c[0] <= hi[0] and lo[1] <= c[1] <= hi[1]}
        self.grid.forget(forget)
        self.rescan |= forget
        moved = ", ".join(data.get("moved_blocks", []))
        if data.get("kind") == "block_added":
            self.change = f"re-scan where {moved} was dropped"
        else:
            self.change = f"re-scan after the {data.get('kind', 'change')} moved {moved}"
        self.target = None

    # ---- one decision a second --------------------------------------------------

    def tick(self, t):
        """The scout/goto to publish now, or None (nothing to do, or a hold is in force)."""
        if self.pose is None:
            return None
        if self.hold:
            target, until, reason = self.hold
            here = centre(target, self.pose[2]) if isinstance(target, tuple) else target
            if t > until or math.dist(here[:2], self.pose[:2]) < REACHED:
                self.hold = None
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
        self.rescan = {c for c in self.rescan if self.grid.state(c) == "unknown"}
        found = self._nearest_frontier()
        if found is None and self.rescan:
            self.rescan = set()
            found = self._nearest_frontier()
        if found is None:
            self.target = None
            return None
        self.target, unknown, path = found
        if self.rescan:
            why = f"{self.change}: frontier at cell {list(self.target)}"
        else:
            why = f"frontier at cell {list(self.target)}"
        return self._send(path, f"{why}, {unknown} unknown neighbours")

    # ---- map helpers ------------------------------------------------------------

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
        if self.bounds and not (self.bounds[0][0] <= i <= self.bounds[1][0] and self.bounds[0][1] <= j <= self.bounds[1][1]):
            return False
        if not any((i + di, j + dj, k) not in self.grid.cells for di, dj in SIDES):
            return False
        if self.rescan and not any((i + di, j + dj, k) in self.rescan for di in range(-2, 3) for dj in range(-2, 3)):
            return False
        return self._unknown_near(i, j) >= MIN_UNKNOWN

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
