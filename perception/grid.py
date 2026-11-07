"""Live occupancy map from the Scout's LiDAR, every 0.05 m cell seen, inferred or unknown (T08).

A cell is `[i, j, k]` = floor(position / 0.05) in the scene frame. Only `seen` cells were measured;
`inferred` cells are guesses (a wall's hidden interior); a cell not in the map is `unknown`.
"""

import math

RES = 0.05
MAX_RANGE = 6.0
FACES = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
SIDES = FACES[:4]     # in-layer neighbours: the map is one LiDAR layer thick, so up and down are unknown
WALLED = 3            # an unknown cell with this many seen, occupied side neighbours is inferred


def cell_of(p, res=RES):
    """Grid index of a point in the scene frame."""
    return tuple(math.floor(v / res) for v in p)


class Grid:
    def __init__(self, res=RES):
        self.res = res
        self.cells = {}        # (i, j, k) -> {"state", "occupied", "hits"}; missing means unknown
        self.changed = set()   # cells whose state or occupied flag changed since the last message

    def state(self, c):
        cur = self.cells.get(tuple(c))
        return cur["state"] if cur else "unknown"

    def _set(self, c, state, occupied):
        cur = self.cells.get(c)
        if cur is None:
            cur = self.cells[c] = {"state": state, "occupied": occupied, "hits": 0}
            self.changed.add(c)
        elif (cur["state"], cur["occupied"]) != (state, occupied):
            cur["state"], cur["occupied"] = state, occupied
            self.changed.add(c)
        return cur

    def hit(self, c):
        """A LiDAR return in cell c: seen and occupied."""
        self._set(c, "seen", True)["hits"] += 1

    def free(self, c):
        """A ray passed through cell c: seen and free, unless a ray has hit it before.

        A return beats a pass: a wall's face cell is partly free space, so a ray grazing the wall
        can pass through it. Clearing cells a moved block left is the hazard re-scan's job.
        """
        cur = self.cells.get(c)
        if cur is None or cur["hits"] == 0:
            self._set(c, "seen", False)

    def infer(self, around):
        """Unknown side neighbours of `around` with 3 or 4 seen, occupied side neighbours become inferred.

        Only the four neighbours in the same layer count: the LiDAR scans one layer, so the cells above
        and below are never seen and a 3D rule (5 of 6 faces) would never fire.
        """
        for c in around:
            for f in SIDES:
                n = (c[0] + f[0], c[1] + f[1], c[2] + f[2])
                if n not in self.cells and self._walled(n) >= WALLED:
                    self._set(n, "inferred", True)

    def _walled(self, c):
        count = 0
        for f in SIDES:
            cur = self.cells.get((c[0] + f[0], c[1] + f[1], c[2] + f[2]))
            count += bool(cur and cur["state"] == "seen" and cur["occupied"])
        return count

    def add_scan(self, pos, ranges, max_range=MAX_RANGE):
        """One LiDAR sweep from `pos`: ray k points at 2*pi*k/n in the scene frame, as sim casts it.

        Each ray is walked in res steps. A range of max_range or more is a miss and marks nothing: no
        return is no measurement (dust and glass drop returns), and it keeps the map to the building.
        """
        x, y, z = pos
        n = len(ranges)
        hits = set()
        for k, r in enumerate(ranges):
            if r >= max_range:
                continue
            a = 2 * math.pi * k / n
            dx, dy = math.cos(a), math.sin(a)
            s = 0.0
            while s < r:
                self.free(cell_of((x + s * dx, y + s * dy, z), self.res))
                s += self.res
            c = cell_of((x + r * dx, y + r * dy, z), self.res)
            self.hit(c)
            hits.add(c)
        self.infer(hits)

    def add_sensors(self, data):
        """Update from one sensors/scout payload: {"pose": {"pos": [x, y, z], ...}, "lidar": [ranges]}."""
        self.add_scan(data["pose"]["pos"], data["lidar"])

    def counts(self):
        out = {"seen": 0, "inferred": 0, "occupied": 0}
        for cur in self.cells.values():
            out[cur["state"]] += 1
            out["occupied"] += cur["occupied"]
        return out

    def delta(self, t):
        """map/cells with only the cells changed since the last message."""
        return self._message(t, self.changed)

    def snapshot(self, t):
        """map/cells with every cell observed so far."""
        return self._message(t, self.cells)

    def _message(self, t, keys):
        cells = [{"cell": list(c), "state": self.cells[c]["state"], "occupied": self.cells[c]["occupied"]}
                 for c in sorted(keys)]
        self.changed = set()
        return {"t": round(t, 2), "res": self.res, "cells": cells}
