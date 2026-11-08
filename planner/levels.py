"""L4 multi-level A*: routes between levels on a map whose k is floor height (perception/levels.py).

Cells are [i, j, k] with k = round(floor height / res), so ground is k = 0 and goals may sit on any level
(L1 k = 12, B1 k = -12 in sim/scenes/levels.xml). A move goes to one of the 8 plan-view neighbours and
may change k by at most MAX_DK per cell (5 cm of height per 5 cm cell, 45 degrees), so the only way
between levels is a measured ramp; an edge or a hole is a jump of many k and never a move.

Only `seen`, unoccupied cells are walked. Cells within KEEP_OUT of an occupied cell on the same level
(see LEVEL_BAND) are never entered (the robot's half width) and cells within CLEARANCE cost extra.
If the goal is not reachable on what is known, find_route returns a reachable frontier cell (one
beside unknown space): the one with the lowest path cost plus GOAL_WEIGHT times its 3D distance to
the goal, so the Scout explores near first and toward the goal on ties (needs "explore").
Pure Python; no physics claim. The sim's physics check still applies to any Responder route.
"""

from __future__ import annotations

from heapq import heappop, heappush
from math import ceil, hypot

Cell = tuple[int, int, int]
NEIGHBOURS = tuple((dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy)
MAX_DK = 1            # k steps allowed per cell moved
LEVEL_BAND = 3        # an occupied cell at kk blocks a floor at k when 0 <= kk - k <= LEVEL_BAND:
                      # perception marks a LiDAR return in the cell of the Scout's floor, and the return
                      # itself is 0.075 m above it, so kk - k in 0..3 puts the return between 0.03 m and
                      # 0.25 m above floor k (a kerb or wall to this robot). A return below k is the
                      # floor or ramp under it; one far above is a slab overhead.
KEEP_OUT = 0.10       # metres from an occupied cell that are never entered
CLEARANCE = 0.20      # metres from an occupied cell that cost CLEARANCE_COST extra per cell
CLEARANCE_COST = 0.5
SNAP_DK = 3           # a goal snaps to a known floor cell in its column this many k away
SEGMENT = 1.0         # metres: waypoints are at most this far apart
GOAL_WEIGHT = 0.5     # frontier score = path cost + GOAL_WEIGHT * distance to the goal


def _index(map_cells: dict) -> tuple[float, dict[tuple[int, int], dict[int, dict]]]:
    res = map_cells["res"]
    cols: dict[tuple[int, int], dict[int, dict]] = {}
    for rec in map_cells["cells"]:
        i, j, k = rec["cell"]
        if rec["state"] == "unknown":
            continue
        cols.setdefault((i, j), {})[k] = rec
    return res, cols


def _disc(radius_cells):
    return [(di, dj) for di in range(-radius_cells, radius_cells + 1)
            for dj in range(-radius_cells, radius_cells + 1) if hypot(di, dj) <= radius_cells]


class Levels:
    def __init__(self, map_cells: dict, hazards: list[dict] | None = None):
        self.res, self.cols = _index(map_cells)
        self.keep = ceil(KEEP_OUT / self.res - 1e-9)
        self.clear = ceil(CLEARANCE / self.res - 1e-9)
        self.blocked = {tuple(h["cell"]) for h in hazards or [] if h.get("status") != "stable"}
        self._walk: dict[Cell, bool] = {}
        self._near: dict[tuple[Cell, int], bool] = {}
        self._occ: dict[tuple[int, int], list[int]] = {}       # column -> occupied k values
        for (i, j), col in self.cols.items():
            ks = [kk for kk, rec in col.items() if rec["occupied"]]
            if ks:
                self._occ[(i, j)] = ks
        self._discs = {r: _disc(r) for r in (self.keep, self.clear)}

    def occupied_near(self, c: Cell, radius_cells: int) -> bool:
        """An occupied cell within radius_cells of c that blocks c's floor (see LEVEL_BAND)."""
        key = (c, radius_cells)
        if key not in self._near:
            i, j, k = c
            self._near[key] = any(0 <= kk - k <= LEVEL_BAND
                                  for di, dj in self._discs[radius_cells]
                                  for kk in self._occ.get((i + di, j + dj), ()))
        return self._near[key]

    def floor(self, i, j, k, band=MAX_DK):
        """The walkable floor cell in column (i, j) closest to k within band, or None."""
        best = None
        for kk, rec in (self.cols.get((i, j)) or {}).items():
            usable = abs(kk - k) <= band and rec["state"] == "seen" and not rec["occupied"]
            if usable and (best is None or abs(kk - k) < abs(best - k)):
                best = kk
        return None if best is None else (i, j, best)

    def walkable(self, c: Cell) -> bool:
        if c not in self._walk:
            self._walk[c] = (self.floor(*c, band=0) is not None and c not in self.blocked
                             and not self.occupied_near(c, self.keep))
        return self._walk[c]

    def neighbours(self, c: Cell):
        i, j, k = c
        for dx, dy in NEIGHBOURS:
            n = self.floor(i + dx, j + dy, k)
            if n is None or not self.walkable(n):
                continue
            if dx and dy and (self.floor(i + dx, j, k) is None or self.floor(i, j + dy, k) is None):
                continue               # never cut a corner
            step = hypot(dx, dy, n[2] - k) * self.res
            extra = CLEARANCE_COST if self.occupied_near(n, self.clear) else 0.0
            yield n, step + extra

    def unknown_beside(self, c: Cell) -> bool:
        """True if a plan-view neighbour has no known cell within MAX_DK of c's level (unexplored)."""
        i, j, k = c
        for dx, dy in NEIGHBOURS:
            col = self.cols.get((i + dx, j + dy)) or {}
            if not any(abs(kk - k) <= MAX_DK for kk in col):
                return True
        return False

    def dist(self, a: Cell, b: Cell) -> float:
        return hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) * self.res


def find_route(map_cells: dict, hazards: list[dict] | None, start, goal) -> dict:
    """{"status": "ok", "cells": [...], "cost"} or {"status": "explore", "frontier": cell, "cells": [...]}
    (the path to that frontier) or {"status": "no_route", "cells": []}."""
    lv = Levels(map_cells, hazards)
    s = lv.floor(*start, band=SNAP_DK) or tuple(start)
    lv._walk[s] = True          # the robot stands here: it is floor, and keep-out is for where it goes
    g = lv.floor(*goal, band=SNAP_DK)
    target = tuple(goal)
    costs, parents = {s: 0.0}, {}
    queue = [(lv.dist(s, target), 0.0, s)]
    done = set()
    best_frontier = None
    while queue:
        _, cost, cur = heappop(queue)
        if cur in done:
            continue
        done.add(cur)
        if g is not None and cur == g:
            return {"status": "ok", "cells": _path(parents, s, cur), "cost": round(cost, 3)}
        if lv.unknown_beside(cur):
            key = (cost + GOAL_WEIGHT * lv.dist(cur, target), cost)
            if best_frontier is None or key < best_frontier[0]:
                best_frontier = (key, cur)
        for n, step in lv.neighbours(cur):
            c2 = cost + step
            if c2 < costs.get(n, float("inf")):
                costs[n], parents[n] = c2, cur
                heappush(queue, (c2 + lv.dist(n, target), c2, n))
    if best_frontier is None:
        return {"status": "no_route", "reason": "goal unreachable and nothing left to explore", "cells": []}
    f = best_frontier[1]
    return {"status": "explore", "frontier": list(f), "cells": _path(parents, s, f)}


def _path(parents, s, cur):
    path = [cur]
    while path[-1] != s:
        path.append(parents[path[-1]])
    return [list(c) for c in reversed(path)]


def waypoints(cells: list[list[int]], res: float = 0.05, segment: float = SEGMENT) -> list[list[float]]:
    """scout/goto targets [x, y, floor z] along a route: at every turn, every change of slope, and at
    most `segment` metres apart, ending at the last cell. z is the floor height, which sim.levels
    honours (the Scout has arrived only on the target's level)."""
    if not cells:
        return []

    def centre(c):
        return [round((c[0] + 0.5) * res, 3), round((c[1] + 0.5) * res, 3), round(c[2] * res, 3)]

    out, last = [], cells[0]
    run = 0.0
    for a, b, c in zip(cells, cells[1:], cells[2:], strict=False):
        run += hypot(b[0] - a[0], b[1] - a[1]) * res
        turn = (b[0] - a[0], b[1] - a[1]) != (c[0] - b[0], c[1] - b[1])
        slope_change = (b[2] - a[2] != 0) != (c[2] - b[2] != 0) and run > 0.3
        if (turn or slope_change or run >= segment) and b != last:
            out.append(centre(b))
            last, run = b, 0.0
    out.append(centre(cells[-1]))
    return out
