"""Hazard prediction: every block's floor cells labelled stable, at_risk or collapsed, always as estimates (T11).

Before the aftershock, from the scene/loaded block boxes (axis-aligned, no rotation):
  (a) a wall taller than it is wide is at_risk when under half its base footprint rests on the floor
      or on the top of another block;
  (b) a rubble block is at_risk when its centre of mass (the box centre) lies outside the convex hull
      of its contact patches with what is directly beneath it, or when nothing is beneath it;
  (c) a wall that an at_risk rubble block touches is at_risk: it carries the leaning block's load.
After a world/change, the cells of each moved block become collapsed and cells within 0.15 m of
them at_risk; every other cell keeps its label.

Cells are the plan-view footprint of each block on the ground layer k=0, the layer map/cells uses
and the planner routes on.
"""

from perception.grid import cell_of

TOL = 0.02            # metres: a bottom face this close to a top face rests on it
SUPPORTED = 0.5       # a wall needs at least this share of its base resting on something
NEAR = 0.15           # metres around a moved block that become at_risk
FLOOR = ((-3.0, -3.0), (3.0, 3.0))    # the backup scene's ground plate, top at z = 0
LAYERS = (0,)        # the ground layer, like map/cells
RANK = {"stable": 0, "at_risk": 1, "collapsed": 2}


def _rect(b, grow=0.0):
    (x, y, _), (sx, sy, _) = b["pos"], b["size"]
    return (x - sx - grow, y - sy - grow), (x + sx + grow, y + sy + grow)


def _overlap(a, b):
    lo = (max(a[0][0], b[0][0]), max(a[0][1], b[0][1]))
    hi = (min(a[1][0], b[1][0]), min(a[1][1], b[1][1]))
    return (lo, hi) if lo[0] < hi[0] and lo[1] < hi[1] else None


def _area(r):
    return (r[1][0] - r[0][0]) * (r[1][1] - r[0][1])


def _hull(points):
    """Convex hull, counter-clockwise (Andrew's monotone chain)."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _inside(p, hull):
    if len(hull) < 3:
        return False
    for a, b in zip(hull, hull[1:] + hull[:1]):
        if (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) < 0:
            return False
    return True


def supports(block, blocks):
    """Contact patches (plan-view rectangles) between `block`'s base and what lies directly beneath it."""
    bottom = block["pos"][2] - block["size"][2]
    base = _rect(block)
    out = []
    if abs(bottom) < TOL:
        patch = _overlap(base, FLOOR)
        if patch:
            out.append(patch)
    for other in blocks:
        if other is block or abs(other["pos"][2] + other["size"][2] - bottom) >= TOL:
            continue
        patch = _overlap(base, _rect(other))
        if patch:
            out.append(patch)
    return out


def risk(block, blocks):
    """The reason `block` is at_risk before any shake, or None if it looks stable."""
    patches = supports(block, blocks)
    sx, sy, sz = block["size"]
    if block.get("label") == "wall" and sz > min(sx, sy):
        share = min(1.0, sum(_area(p) for p in patches) / _area(_rect(block)))
        if share < SUPPORTED:
            return f"unsupported wall {block['id']} ({share:.0%} of its base rests on anything)"
        return None
    if block.get("label") == "rubble":
        if not patches:
            return f"rubble {block['id']} has nothing beneath it: leaning or wedged"
        corners = [(x, y) for lo, hi in patches for x in (lo[0], hi[0]) for y in (lo[1], hi[1])]
        if not _inside(tuple(block["pos"][:2]), _hull(corners)):
            return f"rubble {block['id']} has its centre of mass beyond its support"
    return None


def _touches(a, b):
    """True if boxes a and b overlap or touch (within TOL) in x, y and z."""
    return all(abs(a["pos"][i] - b["pos"][i]) <= a["size"][i] + b["size"][i] + TOL for i in range(3))


def risks(blocks):
    """{block id: why} for every at_risk block: rules (a) and (b), then (c) a wall that an at_risk
    rubble block leans on carries its load, so it is at_risk too (in the backup scene, b8 under b10)."""
    out = {b["id"]: why for b in blocks if (why := risk(b, blocks))}
    for r in blocks:
        if r.get("label") != "rubble" or r["id"] not in out:
            continue
        for w in blocks:
            if w.get("label") == "wall" and w["id"] not in out and _touches(r, w):
                out[w["id"]] = f"wall {w['id']} carries leaning rubble {r['id']}"
    return out


def _cells(rect):
    lo = cell_of([rect[0][0], rect[0][1], 0])
    hi = cell_of([rect[1][0] - 1e-9, rect[1][1] - 1e-9, 0])
    return [(i, j) for i in range(lo[0], hi[0] + 1) for j in range(lo[1], hi[1] + 1)]


class Hazards:
    def __init__(self):
        self.blocks = []
        self.labels = {}          # (i, j) -> (status, why)

    def _mark(self, ij, status, why):
        cur = self.labels.get(ij)
        if cur is None or RANK[status] > RANK[cur[0]]:
            self.labels[ij] = (status, why)

    def on_scene(self, data):
        """Label every block's footprint from its support; return the map/hazards message."""
        self.blocks = data["blocks"]
        self.labels = {}
        flagged = risks(self.blocks)
        for b in self.blocks:
            why = flagged.get(b["id"])
            for ij in _cells(_rect(b)):
                self._mark(ij, "at_risk" if why else "stable", why or f"{b.get('label', 'block')} {b['id']} supported")
        return self.message()

    def on_change(self, data):
        """Moved blocks' cells become collapsed and their 0.15 m surroundings at_risk; return map/hazards."""
        by_id = {b["id"]: b for b in self.blocks}
        moved = [by_id[b] for b in data.get("moved_blocks", []) if b in by_id]
        for b in moved:
            for ij in _cells(_rect(b, NEAR)):
                self._mark(ij, "at_risk", f"next to {b['id']}, which moved in the {data.get('kind', 'change')}")
        for b in moved:
            for ij in _cells(_rect(b)):
                self.labels[ij] = ("collapsed", f"{b.get('label', 'block')} {b['id']} moved in the {data.get('kind', 'change')}")
        return self.message()

    def message(self):
        return [{"cell": [i, j, k], "status": s, "why": why, "estimate": True}
                for (i, j), (s, why) in sorted(self.labels.items()) for k in LAYERS]

    def status(self, ij):
        return self.labels.get(tuple(ij), ("stable", ""))[0]

