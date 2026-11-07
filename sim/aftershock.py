"""The scripted aftershock and the physics route check (T05).

- `shake_offset(t)`: ground displacement at t seconds into an aftershock.
- `aftershock_effects(m, d)`: shake a COPY of the world and return the blocks that move. Never
  touches the live data.
- `unstable_xy(m, d)`: the (i, j) grid columns within MARGIN of any block that would move, using
  perception's grid (cell = floor(coordinate / RES), origin at the scene origin).
- `verify(route, unstable, moved)`: the `route/verified` payload for a `route/proposed` message.

Cells are compared on (i, j) only, so a route on layer k=0 and a map on layer k=1 agree.
"""

import math

import mujoco
import numpy as np

from sim import scene

AMPLITUDE = 0.015      # metres; 0.012-0.018 all fail the same pair (b10, b8) in the backup scene
FREQ = 4.0             # Hz
SHAKE = 2.0            # seconds of shaking
SETTLE = 1.0           # seconds of settling afterwards
DURATION = SHAKE + SETTLE
MOVED = 0.05           # a block that ends more than this far from where it started has moved
RES = 0.05             # perception's grid resolution
MARGIN = 0.10          # cells this close to a moved block's box (before or after) are unstable


def shake_offset(t):
    """[x, y, z] displacement of the ground at t seconds since the aftershock began."""
    x = AMPLITUDE * math.sin(2 * math.pi * FREQ * t) if 0 <= t < SHAKE else 0.0
    return [x, 0.0, 0.0]


def ground_mocap(m):
    return int(m.body_mocapid[m.body("ground").id])


def candidate_blocks(m):
    """Block body ids plus any spare block already dropped into the scene (they are all free bodies)."""
    return scene.block_ids(m) + [b for b in spare_ids(m) if m.body_gravcomp[b] == 0]


def spare_ids(m):
    return [i for i in range(m.nbody) if (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i) or "").startswith("x")]


def body_name(m, i):
    return mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i)


def aftershock_effects(m, d, threshold=MOVED):
    """Run the aftershock on a copy of `d`. Returns (moved body ids, {id: (start box, end box)}).

    A box is (centre xy, half extents xy) of the body's world-aligned bounding box.
    """
    sim = mujoco.MjData(m)
    mujoco.mj_copyData(sim, m, d)
    ids = candidate_blocks(m)
    start = {i: _box(m, sim, i) for i in ids}
    start_pos = sim.xpos[ids].copy()
    k = ground_mocap(m)
    base = sim.mocap_pos[k].copy()
    for step in range(round(DURATION / m.opt.timestep)):
        sim.mocap_pos[k] = base + shake_offset(step * m.opt.timestep)
        mujoco.mj_step(m, sim)
    sim.mocap_pos[k] = base
    moved = [i for i, p0 in zip(ids, start_pos, strict=True) if np.linalg.norm(sim.xpos[i] - p0) > threshold]
    return moved, {i: (start[i], _box(m, sim, i)) for i in moved}


def _box(m, d, body):
    """World-aligned bounding box of a body's geoms: (centre xy, half extents xy)."""
    lo, hi = np.full(2, np.inf), np.full(2, -np.inf)
    for g in range(m.body_geomadr[body], m.body_geomadr[body] + m.body_geomnum[body]):
        half = np.abs(d.geom_xmat[g].reshape(3, 3)) @ m.geom_size[g]   # box half extents in the world
        c = d.geom_xpos[g]
        lo = np.minimum(lo, c[:2] - half[:2])
        hi = np.maximum(hi, c[:2] + half[:2])
    return (lo + hi) / 2, (hi - lo) / 2


def cells_near(box, margin=MARGIN, res=RES):
    """(i, j) columns whose square comes within `margin` of the box."""
    centre, half = box
    lo, hi = centre - half - margin, centre + half + margin
    i0, j0 = (math.floor(v / res) for v in lo)
    i1, j1 = (math.floor(v / res) for v in hi)
    return {(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)}


def unstable_xy(m, d):
    """(set of (i, j) columns that an aftershock now would make unsafe, list of moved block names)."""
    moved, boxes = aftershock_effects(m, d)
    cells = set()
    for before, after in boxes.values():
        cells |= cells_near(before) | cells_near(after)
    return cells, [body_name(m, i) for i in moved]


def verify(route, unstable, moved):
    """`route/verified` payload for a `route/proposed` message, given a cached unstable set."""
    bad = [list(c) for c in route["cells"] if (c[0], c[1]) in unstable]
    if bad:
        detail = f"{len(bad)} route cells are next to {', '.join(moved)}, which an aftershock would move"
    elif moved:
        detail = f"an aftershock would move {', '.join(moved)}, none of it on this route"
    else:
        detail = "no block moves in a simulated aftershock"
    return {"id": route["id"], "ok": not bad, "unstable_cells": bad, "detail": detail}
