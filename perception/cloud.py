"""Pile stability from the Scout's own 3D points (Z1), never from sim block poses.

The depth camera's points (`sensors/scout.points`, scene frame) are binned into the map's 0.05 m
plan columns, keeping each column's lowest and highest point. Two things make a pile unstable:

  overhang  a column whose points all sit OVERHANG_Z or more above floor that the LiDAR saw open:
            mass with nothing under it (a slab leaning across a gap);
  motion    columns the scan diff (grid.appeared / grid.cleared) saw change in the last MOTION_S
            seconds: a pile that just moved can move again (secondary fall).

A column's stability is 1 - (OVERHANG_W * overhang share + MOTION_W * motion share) over the
occupied columns within WINDOW cells (0.2 m), clipped to 0..1; below AT_RISK it is at_risk. Overhang
columns, and the columns within SUPPORT cells that carry them, are scored the same way, so a wall a
slab leans on scores low and an outer wall far from it scores 1.

Without points (no depth camera yet) only motion counts: the 2D LiDAR at 0.075 m cannot see a slab
0.3 m up.
"""

import math

from perception.grid import RES

FLOOR_Z = 0.03        # points below this are the floor
OVERHANG_Z = 0.15     # a column's lowest point at least this high, over open floor, overhangs
MIN_POINTS = 2        # points a column needs before it counts
WINDOW = 4            # cells: the neighbourhood a column's stability is scored over (0.2 m)
SUPPORT = 2           # cells around an overhang whose occupied columns carry it (0.1 m)
AT_RISK = 0.5
MOTION_S = 30.0
OVERHANG_W, MOTION_W = 1.5, 1.0


def _near(cells, r):
    out = set()
    for i, j in cells:
        out.update((i + di, j + dj) for di in range(-r, r + 1) for dj in range(-r, r + 1) if di * di + dj * dj <= r * r)
    return out


class Cloud:
    def __init__(self, res=RES):
        self.res = res
        self.columns = {}     # (i, j) -> [lowest z, highest z, points]

    def reset(self):
        """Forget every point (after a shake the old ones describe a pile that may have moved)."""
        self.columns = {}

    def add(self, points):
        for x, y, z in points:
            if z < FLOOR_Z:
                continue
            ij = (math.floor(x / self.res), math.floor(y / self.res))
            col = self.columns.get(ij)
            if col is None:
                self.columns[ij] = [z, z, 1]
            else:
                col[0], col[1], col[2] = min(col[0], z), max(col[1], z), col[2] + 1

    def add_sensors(self, data):
        if data.get("points"):
            self.add(data["points"])

    def overhangs(self, grid):
        """{(i, j): (lowest, highest)} for columns whose points float above floor the LiDAR saw open."""
        return {ij: (lo, hi) for ij, (lo, hi, n) in self.columns.items()
                if n >= MIN_POINTS and lo >= OVERHANG_Z and grid.column(*ij) == ("seen", False)}

    def solid(self, grid):
        """Occupied plan columns: the LiDAR's occupied cells plus point columns that reach the floor."""
        out = {(c[0], c[1]) for c, cur in grid.cells.items() if cur["occupied"]}
        out |= {ij for ij, (lo, _, n) in self.columns.items() if n >= MIN_POINTS and lo < OVERHANG_Z}
        return out

    def stability(self, grid, now):
        """{(i, j): (score 0..1, why)} for every column near an overhang or recent motion; others are 1."""
        over = self.overhangs(grid)
        recent = {(c[0], c[1]) for d in (grid.appeared, grid.cleared) for c, t in d.items() if now - t <= MOTION_S}
        solid = self.solid(grid)
        body = solid | set(over)
        scored = (set(over) | (_near(over, SUPPORT) & solid) | (_near(recent, WINDOW) & body))
        out = {}
        for ij in scored:
            window = _near([ij], WINDOW) & (body | recent)
            n_over = len(window & set(over))
            n_moved = len(window & recent)
            share = max(1, len(window))
            score = max(0.0, min(1.0, 1 - OVERHANG_W * n_over / share - MOTION_W * n_moved / share))
            if ij in over:
                lo, hi = over[ij]
                why = f"overhang {lo:.2f}-{hi:.2f} m above open floor"
            elif n_over:
                why = f"carries an overhang ({n_over} overhanging columns within 0.2 m)"
            else:
                why = f"{n_moved} columns within 0.2 m moved in the last {MOTION_S:.0f} s"
            out[ij] = (round(score, 2), f"pile stability {score:.2f}: {why}")
        return out

    def risks(self, grid, now):
        """{(i, j): why} for columns whose stability is below AT_RISK."""
        return {ij: why for ij, (score, why) in self.stability(grid, now).items() if score < AT_RISK}
