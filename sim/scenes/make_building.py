"""Generate sim/scenes/building.xml: a true-scale multi-storey building after an earthquake (ref Y1b).

    python -m sim.scenes.make_building            # seed 7; a few minutes of physics
    python -m sim.scenes.make_building --seed 3

How it is made (all physics, fixed seed, so the same seed gives the same building):
1. An intact reinforced-concrete frame, 12 m x 9 m, three storeys of 3 m: 4 x 3 columns per storey,
   one slab per bay per floor, ground and first storey infill walls with 0.9 m doors (sized for the
   true-scale robots, sim/robots), an exterior stair on the west side. Every connection
   (column-slab, column-column, wall-column) is a weld.
2. The main shock: the east ground-storey columns (x = 12) have failed, and the ground shakes hard for
   a few seconds. Nothing is placed by hand after this: welds break past their force limit
   (sim/breakage.py), slabs fall, tilt and pancake, and seeded rubble chunks rain onto the collapse.
3. Everything settles; the settled poses become the scene. Broken welds are left out.
4. Casualties go into covered voids found by ray tests (a roof within 1.5 m, 0.35 m clear around),
   spread apart; one more in an intact room, silent.
5. Breaking strengths are calibrated from the static force on each surviving weld: most get a wide
   margin; the ground-storey wall joints in the middle bay get just above their static load, so the
   in-demo aftershock (0.015 m at 4 Hz) breaks them and the panels fall into the rooms.
6. The true-scale Scout and Responder (sim/robots) are attached outside the south door; the ground
   is a mocap body with a welded floor plate, as in the other scenes. Settled bodies sleep (MuJoCo 4).
"""

import argparse
import os
import pathlib
import pickle

import mujoco
import numpy as np

from sim import aftershock, breakage, robots

OUT = pathlib.Path(__file__).parent / "building.xml"
XS = (0.0, 4.0, 8.0, 12.0)
YS = (0.0, 4.5, 9.0)
STOREY = 3.0
SLAB_T = 0.2
COL = 0.15                 # column half width
WALL_T = 0.1               # wall half thickness
DOOR = 0.9
G = 0.004                  # gap between pieces
DENSITY = 2400.0           # reinforced concrete, kg/m^3
SOUND = 6.0                # a sound joint breaks at 6x its static load
WEAK = 2.0                 # a cracked joint (the live middle bay) at 2x its peak load at rest: the aftershock breaks it
FLOOR_N, FLOOR_NM = 2.0e3, 1.0e3   # no limit below these, so lightly loaded welds do not break on noise
DEBRIS_CAP = int(os.environ.get("BUILDING_DEBRIS", "250"))   # smaller for quick tuning runs
MAIN_SHOCK = 0.02           # m at 2 Hz for 2 s: the damage, not the shake, brings the east bay down
INTACT_MARGIN = 8.0        # main-shock limits: 8x each joint's static load in the intact frame
FAILED_X = 12.0            # the ground-storey columns on this line have failed

CONCRETE = "0.62 0.61 0.58 1"
CONCRETE_DARK = "0.5 0.49 0.47 1"
WALL_RGBA = "0.72 0.66 0.56 1"
RUBBLE_RGBA = "0.55 0.53 0.5 1"
FURNITURE_RGBA = "0.45 0.34 0.24 1"
WARMUP_S = 0.5             # = sim/world.py WARMUP_S: settling before welds may break
SETTLE_S = 0.5             # main shock: welds can break only after this much settling
HINGE_MARGIN = 1.5         # the east slabs' cracked hinges hold 1.5x their intact static load


class Building:
    def __init__(self, seed):
        self.rng = np.random.default_rng(seed)
        self.pieces = []       # dicts: name, label, pos, size, rgba, quat, geoms (extra), density
        self.welds = []        # (piece a, piece b, kind)
        self.keys = {"plate": "plate"}   # piece name -> stable key

    def piece(self, label, lo, hi, rgba, kind=None, key=None):
        """Add a box piece; `key` is a stable id (the b<n> names shift when failed columns are left out)."""
        c = [(a + b) / 2 for a, b in zip(lo, hi, strict=True)]
        s = [(b - a) / 2 for a, b in zip(lo, hi, strict=True)]
        name = f"b{len(self.pieces) + 1}"
        key = key or (label, len([p for p in self.pieces if p["label"] == label]))
        self.pieces.append({"name": name, "label": label, "pos": c, "size": s, "rgba": rgba, "kind": kind,
                            "quat": [1, 0, 0, 0], "extra": [], "key": key})
        self.keys[name] = key
        return name

    def weld(self, a, b, kind):
        self.welds.append((a, b, kind))

    # ---- the intact frame (minus the failed columns) ------------------------------------
    def frame(self, failed=True):
        self.failed = failed
        cols = {}
        slabs = {}
        for s in range(3):
            z0 = s * STOREY
            for x in XS:
                for y in YS:
                    if failed and x == FAILED_X:
                        continue                       # shattered in the main shock (every storey)
                    lo = (x - COL, y - COL, z0 + G)
                    hi = (x + COL, y + COL, z0 + STOREY - SLAB_T - G)
                    cols[s, x, y] = self.piece("column", lo, hi, CONCRETE_DARK, key=("column", s, x, y))
            for bx in range(3):
                for by in range(2):
                    lo = (XS[bx] + G, YS[by] + G, z0 + STOREY - SLAB_T)
                    hi = (XS[bx + 1] - G, YS[by + 1] - G, z0 + STOREY)
                    slabs[s, bx, by] = self.piece("slab", lo, hi, CONCRETE, key=("slab", s, bx, by))
        # column - slab (top of each column carries the corners of up to four slabs), slab - column above
        for (s, x, y), c in cols.items():
            for (s2, bx, by), sl in slabs.items():
                if s2 == s and XS[bx] <= x <= XS[bx + 1] and YS[by] <= y <= YS[by + 1]:
                    self.weld(c, sl, "column-slab")
            if s > 0:
                for (s2, bx, by), sl in slabs.items():
                    if s2 == s - 1 and XS[bx] <= x <= XS[bx + 1] and YS[by] <= y <= YS[by + 1]:
                        self.weld(sl, c, "slab-column")
            if s == 0:
                self.weld("plate", c, "footing")
        self.cols, self.slabs = cols, slabs
        # Hinges: the east slabs' joints on the x=8 columns. Cracked: they give way under the new
        # cantilever load once the x=12 line has gone, so the east floors come down.
        east = {slabs[k] for k in slabs if k[1] == 2}
        line8 = {c for (s, x, _y), c in cols.items() if x == XS[2]}
        self.hinges = {(a, c) for a, c, _k in self.welds if (a in line8 and c in east) or (a in east and c in line8)}

    def furniture(self):
        """Heavy furniture in the east bay's ground storey (desks, cabinets): falling slabs land on it."""
        for _ in range(7):
            x, y = self.rng.uniform(8.6, 11.4), self.rng.uniform(0.6, 8.4)
            w, l, h = self.rng.uniform(0.3, 0.45), self.rng.uniform(0.5, 0.8), self.rng.uniform(0.75, 1.0)
            if self.rng.random() < 0.5:
                w, l = l, w
            self.piece("furniture", (x - w, y - l, 0.0), (x + w, y + l, h), FURNITURE_RGBA)

    def walls(self):
        """Ground and first-storey infill between columns; doors on the ground storey."""
        doors = {("S", 0): 2.0, ("Y", 0): 2.0, ("Y", 1): 6.0, ("X", 0): 2.25}
        for s in (0, 1):
            z0, z1 = s * STOREY + G, s * STOREY + STOREY - SLAB_T - G
            edges = []
            for i in range(3):                                   # south and north edges, interior y=4.5
                edges.append(("S", i, (XS[i], YS[0]), (XS[i + 1], YS[0])))
                edges.append(("N", i, (XS[i], YS[2]), (XS[i + 1], YS[2])))
                edges.append(("Y", i, (XS[i], YS[1]), (XS[i + 1], YS[1])))
            for j in range(2):                                   # west edge, interior x=4 and x=8
                edges.append(("W", j, (XS[0], YS[j]), (XS[0], YS[j + 1])))
                edges.append(("X", j, (XS[1], YS[j]), (XS[1], YS[j + 1])))
            for kind, i, a, b in edges:
                if kind == "Y" and i == 2:
                    continue                                     # the east bay is the collapse
                if self.failed and kind in ("S", "N") and i == 2:
                    continue                                     # its perimeter walls failed with the columns
                door = doors.get((kind, i)) if s == 0 else None
                along_x = a[1] == b[1]
                lo_t, hi_t = (a[0], b[0]) if along_x else (a[1], b[1])
                lo_t, hi_t = lo_t + COL + G, hi_t - COL - G
                spans = [(lo_t, hi_t)] if door is None else [(lo_t, door - DOOR / 2), (door + DOOR / 2, hi_t)]
                parts = [(p, q, z0, z1) for p, q in spans]
                if door is not None:
                    parts.append((door - DOOR / 2 + G, door + DOOR / 2 - G, z0 + 2.1, z1))   # lintel
                made = []
                for p, q, za, zb in parts:
                    if along_x:
                        lo, hi = (p, a[1] - WALL_T, za), (q, a[1] + WALL_T, zb)
                    else:
                        lo, hi = (a[0] - WALL_T, p, za), (a[0] + WALL_T, q, zb)
                    w = self.piece("wall", lo, hi, WALL_RGBA, kind=f"{kind}{i}s{s}")
                    made.append(w)
                    if za < z0 + 1.0:
                        if abs(p - lo_t) < 1e-6 and (c := self.cols.get((s, a[0], a[1]))):
                            self.weld(c, w, "wall-column")
                        if abs(q - hi_t) < 1e-6 and (c := self.cols.get((s, b[0], b[1]))):
                            self.weld(c, w, "wall-column")
                        if s == 0:
                            self.weld("plate", w, "wall-footing")
                if door is not None:                             # the lintel hangs on both door jambs
                    self.weld(made[0], made[-1], "wall-column")
                    self.weld(made[1], made[-1], "wall-column")

    def stairs(self):
        """Exterior stair on the west face: 14 steps of 0.2 m up to the first floor."""
        name = f"b{len(self.pieces) + 1}"
        steps = []
        for k in range(14):
            y0 = 0.6 + k * 0.28
            steps.append(((-1.2, y0, 0.0), (-0.2, y0 + 0.28, 0.2 * (k + 1))))
        self.pieces.append({"name": name, "label": "stairs", "pos": None, "size": None, "rgba": CONCRETE_DARK,
                            "kind": None, "quat": [1, 0, 0, 0], "extra": steps, "key": ("stairs",)})
        self.keys[name] = ("stairs",)
        self.weld("plate", name, "footing")
        self.weld(self.cols[0, 0.0, 4.5], name, "wall-column")

    def debris(self):
        """Rubble chunks dropped over the collapse (east bay) and a few against the walls."""
        n = DEBRIS_CAP
        for k in range(n):
            if k < int(n * 0.8):
                x = self.rng.uniform(8.3, 13.0)
                y = self.rng.uniform(0.3, 8.7)
            else:
                x = self.rng.uniform(0.5, 7.5)
                y = self.rng.choice([self.rng.uniform(0.4, 1.0), self.rng.uniform(8.0, 8.6)])
            s = self.rng.uniform(0.06, 0.2, size=3)
            z = 3.5 + (k % 25) * 0.45 if x > 8.0 else 0.3 + (k % 5) * 0.45
            self.piece("rubble", (x - s[0], y - s[1], z - s[2]), (x + s[0], y + s[1], z + s[2]), RUBBLE_RGBA)


def _fmt(v):
    return " ".join(f"{x:.5f}".rstrip("0").rstrip(".") if abs(x) > 1e-9 else "0" for x in v)


def body_xml(p, sleepy=True, static=False):
    """A piece as a body: free (a joint) or static (no joint, a fixed part of the floor plate)."""
    sleep = ' sleep="auto"' if sleepy else ""
    joint = "<freejoint/>"
    if static:
        sleep, joint = ' gravcomp="1"', ""            # carried by the plate: no weight on its weld
    if p["label"] == "stairs":
        geoms = "".join(
            f'<geom name="{p["name"]}_stairs{"" if i == 0 else i}" type="box" pos="{_fmt([(a + b) / 2 for a, b in zip(lo, hi, strict=True)])}" '
            f'size="{_fmt([(b - a) / 2 for a, b in zip(lo, hi, strict=True)])}" density="{DENSITY}" rgba="{p["rgba"]}" material="concrete"/>'
            for i, (lo, hi) in enumerate(p["extra"]))
        pos = p.get("body_pos", [0, 0, 0])
        quat = p.get("body_quat", [1, 0, 0, 0])
        return f'    <body name="{p["name"]}" pos="{_fmt(pos)}" quat="{_fmt(quat)}"{sleep}>{joint}{geoms}</body>'
    mat = "concrete" if p["label"] in ("column", "slab", "rubble") else "plaster"
    density = 600.0 if p["label"] == "furniture" else DENSITY
    return (f'    <body name="{p["name"]}" pos="{_fmt(p["pos"])}" quat="{_fmt(p["quat"])}"{sleep}>{joint}'
            f'<geom name="{p["name"]}_{p["label"]}" type="box" size="{_fmt(p["size"])}" density="{density}" '
            f'rgba="{p["rgba"]}" material="{mat}"/></body>')


HEAD = """<mujoco model="aftershock_building">
  <option timestep="0.002" gravity="0 0 -9.81" noslip_iterations="2" cone="elliptic" impratio="5">
    <flag sleep="enable"/>
  </option>
  <visual>
    <global offwidth="1280" offheight="960"/>
    <quality shadowsize="4096"/>
    <headlight ambient="0.25 0.25 0.25" diffuse="0.35 0.35 0.35"/>
  </visual>
  <default>
    <geom friction="0.8 0.005 0.0001" solref="0.004 1"/>
    <equality solref="0.004 1"/>
  </default>
  <asset>
    <texture name="sky" type="skybox" builtin="gradient" rgb1="0.55 0.58 0.6" rgb2="0.2 0.21 0.23" width="256" height="256"/>
    <texture name="concrete" type="2d" builtin="flat" rgb1="0.62 0.61 0.58" mark="random" random="0.25" markrgb="0.45 0.44 0.42" width="256" height="256"/>
    <texture name="plaster" type="2d" builtin="flat" rgb1="0.75 0.7 0.62" mark="random" random="0.1" markrgb="0.6 0.56 0.5" width="256" height="256"/>
    <texture name="ground" type="2d" builtin="checker" rgb1="0.42 0.4 0.37" rgb2="0.38 0.36 0.34" width="512" height="512"/>
    <material name="concrete" texture="concrete" texrepeat="2 2" texuniform="true" specular="0.05" shininess="0.05"/>
    <material name="plaster" texture="plaster" texrepeat="2 2" texuniform="true" specular="0.02"/>
    <material name="ground" texture="ground" texrepeat="12 12" texuniform="true" specular="0.0"/>
  </asset>
"""

WORLD_HEAD = """  <worldbody>
    <light name="sun" pos="4 -6 14" dir="-0.2 0.4 -1" directional="true" castshadow="true" diffuse="0.75 0.72 0.68"/>
    <light name="fill" pos="6 12 10" dir="0 -0.5 -1" directional="true" castshadow="false" diffuse="0.25 0.27 0.3"/>
    <body name="ground" mocap="true" pos="0 0 0"/>
    <body name="plate" pos="0 0 0">
      <freejoint/>
      <geom name="floor" type="box" size="20 20 0.1" pos="6 4.5 -0.1" density="100" material="ground" rgba="1 1 1 1"/>
    </body>
"""


def intact_xml(b):
    bodies = "\n".join(body_xml(p, sleepy=False) for p in b.pieces)
    welds = "\n".join(f'    <weld body1="{a}" body2="{c}"/>' for a, c, _ in b.welds)
    return (HEAD + WORLD_HEAD + bodies + "\n  </worldbody>\n  <equality>\n"
            '    <weld name="plate_to_ground" body1="plate" body2="ground"/>\n' + welds + "\n  </equality>\n</mujoco>\n")


def stair_frame(p):
    """Stairs: body origin at the first step's centre so the pose round-trips."""
    lo, hi = p["extra"][0]
    o = [(a + c) / 2 for a, c in zip(lo, hi, strict=True)]
    p["extra"] = [([a - oo for a, oo in zip(lo2, o, strict=True)], [c - oo for c, oo in zip(hi2, o, strict=True)])
                  for lo2, hi2 in p["extra"]]
    p["body_pos"] = o


def _weld_keys(b):
    """Stable (key a, key b) per weld, the same in the intact and the damaged frame."""
    return [(b.keys[a], b.keys[c]) for a, c, _ in b.welds]


def intact_limits(seed):
    """{(body a, body b): (force, torque)} at INTACT_MARGIN x the static load in the undamaged frame."""
    b = Building(seed)
    b.frame(failed=False)
    b.walls()
    b.stairs()
    for p in b.pieces:
        if p["label"] == "stairs":
            stair_frame(p)
    m = mujoco.MjModel.from_xml_string(intact_xml(b))
    d = mujoco.MjData(m)
    for _ in range(round(0.6 / m.opt.timestep)):
        mujoco.mj_step(m, d)
    f0, t0 = breakage.weld_loads(m, d)
    out = {}
    for i, (key, (_a, _c, kind)) in enumerate(zip(_weld_keys(b), b.welds, strict=True), start=1):
        if kind == "footing":
            continue
        out[key] = (max(INTACT_MARGIN * f0[i], 5e4), max(INTACT_MARGIN * t0[i], 5e4))
    return out


def main_shock(b, limits, seconds=6.0):
    """Collapse the damaged frame: gravity, a mild shake, rubble, settling. Returns surviving welds."""
    for p in b.pieces:
        if p["label"] == "stairs":
            stair_frame(p)
    m = mujoco.MjModel.from_xml_string(intact_xml(b))
    d = mujoco.MjData(m)
    force, torque = np.zeros(m.neq), np.zeros(m.neq)
    for i, key in enumerate(_weld_keys(b), start=1):
        f, t = limits.get(key, (0.0, 0.0))
        if (b.welds[i - 1][0], b.welds[i - 1][1]) in b.hinges:
            f, t = f * HINGE_MARGIN / INTACT_MARGIN, t * HINGE_MARGIN / INTACT_MARGIN
        force[i], torque[i] = f, t
    breaker = breakage.Breaker(m, force, torque)
    k = int(m.body_mocapid[m.body("ground").id])
    for n in range(round(seconds / m.opt.timestep)):
        t = n * m.opt.timestep
        amp = MAIN_SHOCK if 0.5 < t < 2.5 else 0.0
        d.mocap_pos[k] = [amp * np.sin(2 * np.pi * 2.0 * t), 0.5 * amp * np.sin(2 * np.pi * 1.3 * t), 0]
        mujoco.mj_step(m, d)
        if t > SETTLE_S:                       # the first steps load every weld at once: not damage
            breaker.step(m, d)
    d.mocap_pos[k] = [0, 0, 0]
    # Settle until everything has stopped (pieces freeze where they are, so none may be mid-fall):
    # at least 3 s, then until the fastest piece moves under 2 cm/s, at most 15 s.
    for n in range(round(15.0 / m.opt.timestep)):
        mujoco.mj_step(m, d)
        breaker.step(m, d)
        if n * m.opt.timestep > 3.0 and n % 50 == 0 and np.abs(d.qvel).max() < 0.02:
            break
    for p in b.pieces:
        i = m.body(p["name"]).id
        if p["label"] == "stairs":
            p["body_pos"], p["body_quat"] = d.xpos[i].tolist(), d.xquat[i].tolist()
        else:
            p["pos"], p["quat"] = d.xpos[i].tolist(), d.xquat[i].tolist()
    alive = [w for i, w in enumerate(b.welds, start=1) if d.eq_active[i]]
    lost = [p["name"] for p in b.pieces if d.xpos[m.body(p["name"]).id][2] < -1.0]
    return alive, lost, m, d


def find_voids(m, d, rng, want=3):
    """Points on the ground storey under a low roof with room around them, spread apart."""
    cands = []
    for x in np.arange(0.4, 12.6, 0.2):
        for y in np.arange(0.4, 8.6, 0.2):
            up = mujoco.mj_ray(m, d, np.array([x, y, 0.05]), np.array([0, 0, 1.0]), None, 1, -1, np.zeros(1, np.int32))
            if not 0.45 < up < 1.5:
                continue
            clear = True
            for a in np.linspace(0, 2 * np.pi, 12, endpoint=False):
                r = mujoco.mj_ray(m, d, np.array([x, y, 0.15]), np.array([np.cos(a), np.sin(a), 0]), None, 1, -1,
                                  np.zeros(1, np.int32))
                if 0 <= r < 0.35:
                    clear = False
                    break
            if clear:
                cands.append((x, y, up))
    rng.shuffle(cands)
    picked = []
    for c in cands:
        if all(np.hypot(c[0] - p[0], c[1] - p[1]) > 2.0 for p in picked):
            picked.append(c)
        if len(picked) == want:
            break
    return picked, len(cands)


def build(seed=7, verbose=True):
    say = print if verbose else (lambda *a, **k: None)
    limits = intact_limits(seed)
    b = Building(seed)
    b.frame()
    b.walls()
    b.stairs()
    b.furniture()
    b.debris()
    say(f"{len(b.pieces)} pieces, {len(b.welds)} welds; main shock...")
    alive, lost, m, d = main_shock(b, limits)
    keep = [p for p in b.pieces if p["name"] not in lost]
    say(f"{len(b.welds) - len(alive)} welds broke; {len(lost)} pieces fell off the plate (dropped)")
    voids, n = find_voids(m, d, b.rng)
    say(f"{n} void points; casualties at {[tuple(round(v, 2) for v in p[:2]) for p in voids]}")
    return b, keep, alive, voids


CASUALTY_VOICES = (0.0, 1.0, 0.4, 0.7)


def _aabb(p):
    """World axis-aligned (lo, hi) of a box piece from its centre, half sizes and quaternion."""
    R = np.zeros(9)
    mujoco.mju_quat2Mat(R, np.asarray(p["quat"], float))
    half = np.abs(R.reshape(3, 3)) @ np.asarray(p["size"], float)
    c = np.asarray(p["pos"], float)
    return c - half, c + half


def live_pieces(keep):
    """The pieces the in-demo aftershock can still move: the middle bay (x 4..8) left standing (its floor
    slabs, ground and first-storey walls), the cracked columns on the x = 8 line beside the collapse, and
    whatever rests on them. Everything else is frozen ruin."""
    live = set()
    for p in keep:
        if p["label"] == "stairs":
            continue
        c = p["pos"]
        if p["label"] == "slab" and 4.0 < c[0] < 8.0 and c[2] > 2.5:
            live.add(p["name"])
        if p["label"] == "wall" and 4.2 < c[0] < 7.8 and 0.5 < c[2] < 5.0:
            live.add(p["name"])
        if p["label"] == "column" and abs(c[0] - XS[2]) < 0.3 and c[2] < 5.0:
            live.add(p["name"])                        # cracked columns beside the collapse (x = 8)
    boxes = [_aabb(p) for p in keep if p["name"] in live]
    for p in keep:
        if p["label"] in ("rubble", "furniture") and p["name"] not in live:
            lo, hi = _aabb(p)
            if any(np.all(lo < h2 + 0.05) and np.all(hi > l2 - 0.05) and lo[2] > l2[2] for l2, h2 in boxes):
                live.add(p["name"])
    return live


DOORS = ((2.0, 0.0), (2.0, 4.5), (6.0, 4.5), (4.0, 2.25))   # ground-storey door centres (x, y)


def tidy(keep):
    """Drop rubble lying in a ground-storey doorway (the robots must get through) and pieces the main
    shock threw out of the site (a solver kick, not physics worth keeping)."""
    out = []
    for p in keep:
        lo, hi = _aabb(p) if p["label"] != "stairs" else (np.array([-9.0] * 3), np.array([9.0] * 3))
        c = (lo + hi) / 2
        thrown = hi[2] > 12.0 or not (-3 < c[0] < 15 and -3 < c[1] < 12)
        in_door = p["label"] in ("rubble", "furniture") and lo[2] < 1.5 and any(
            np.hypot(c[0] - x, c[1] - y) < 1.1 for x, y in DOORS)
        if not (thrown or in_door):
            out.append(p)
    return out


def supported(m, d, i, slack=0.3):
    """True if something lies within `slack` below the box of body i, under its centre or a corner."""
    g = m.body_geomadr[i]
    R = d.geom_xmat[g].reshape(3, 3)
    half = np.abs(R) @ m.geom_size[g]
    c = d.geom_xpos[g]
    if c[2] - half[2] < 0.05:
        return True
    for dx, dy in ((0, 0), (0.7, 0.7), (0.7, -0.7), (-0.7, 0.7), (-0.7, -0.7)):
        start = np.array([c[0] + dx * half[0], c[1] + dy * half[1], c[2]])
        hit = mujoco.mj_ray(m, d, start, np.array([0, 0, -1.0]), None, 1, i, np.zeros(1, np.int32))
        if 0 <= hit < half[2] + slack:
            return True
    return False


def drop_unsupported(keep):
    """Remove loose pieces left hanging (repeat: one removal can leave another hanging)."""
    for _ in range(4):
        text = HEAD + WORLD_HEAD + "\n".join(body_xml(p, sleepy=False) for p in keep) + "\n  </worldbody>\n</mujoco>\n"
        m = mujoco.MjModel.from_xml_string(text)
        d = mujoco.MjData(m)
        mujoco.mj_forward(m, d)
        hanging = {p["name"] for p in keep if p["label"] in ("rubble", "furniture")
                   and not supported(m, d, m.body(p["name"]).id)}
        if not hanging:
            break
        keep = [p for p in keep if p["name"] not in hanging]
    return keep


def final_xml(b, keep, alive, voids):
    keep = drop_unsupported(tidy(keep))
    names = {p["name"] for p in keep}
    live = live_pieces(keep)
    alive = [(a, c, k) for a, c, k in alive if (a == "plate" or a in names) and (c == "plate" or c in names)]
    alive = [(a, c, k) for a, c, k in alive if a in live or c in live]       # frozen-to-frozen: one rigid ruin
    statics = "\n".join("  " + body_xml(p, static=True) for p in keep if p["name"] not in live)
    bodies = "\n".join(body_xml(p) for p in keep if p["name"] in live)
    head = WORLD_HEAD.replace('<body name="plate" pos="0 0 0">', '<body name="plate" pos="0 0 0" gravcomp="1">', 1)
    head = head.replace("    </body>\n", statics + "\n    </body>\n", 1)
    cas = [(2.0, 2.2, 0.15)] + [(x, y, 0.15) for x, y, _ in voids]    # c1: west room, in the open
    cas_xml = "\n".join(
        f'    <body name="casualty_c{i + 1}" pos="{x:.2f} {y:.2f} {z}" euler="0 90 0">'
        f'<geom name="c{i + 1}_g" type="capsule" size="0.15 0.6" contype="0" conaffinity="0" rgba="0.85 0.35 0.3 1"/></body>'
        for i, (x, y, z) in enumerate(cas))
    voices = "\n".join(f'    <numeric name="voice_c{i + 1}" data="{CASUALTY_VOICES[i]}"/>' for i in range(len(cas)))
    welds = "\n".join(f'    <weld name="j{i}_{k}" body1="{a}" body2="{c}"/>' for i, (a, c, k) in enumerate(alive))
    spare = ('    <body name="x1" pos="0 -8 -1" gravcomp="1"><freejoint/><geom name="x1_rubble" type="box" '
             'size="0.3 0.3 0.25" density="2000" contype="0" conaffinity="0" material="concrete"/></body>\n')
    supplies = (
        '    <body name="water" pos="2 -2.9 0.16"><freejoint/><geom name="water_supply" type="cylinder" size="0.035 0.06" mass="0.5" group="3" rgba="0.2 0.55 1 1"/></body>\n'
        '    <body name="first_aid_kit" pos="2 -2.8 0.13"><freejoint/><geom name="first_aid_kit_supply" type="box" size="0.05 0.035 0.03" mass="0.4" group="3" rgba="0.9 0.15 0.15 1"/></body>\n'
        '    <body name="radio" pos="2 -2.7 0.145"><freejoint/><geom name="radio_supply" type="box" size="0.025 0.02 0.045" mass="0.3" group="3" rgba="0.15 0.15 0.15 1"/></body>\n'
    )
    carry_welds = (
        '    <weld name="carry_water" body1="responder" body2="water" active="true"/>\n'
        '    <weld name="carry_first_aid_kit" body1="responder" body2="first_aid_kit" active="true"/>\n'
        '    <weld name="carry_radio" body1="responder" body2="radio" active="true"/>\n'
    )
    text = (HEAD + "  <custom>\n" + voices + "\n  </custom>\n" + head + bodies + "\n"
            + cas_xml + "\n" + spare + supplies
            + '    <camera name="overview" pos="6 -11 10" xyaxes="1 0 0 0 0.7 0.71"/>\n'
            + "  </worldbody>\n  <equality>\n"
            + '    <weld name="plate_to_ground" body1="plate" body2="ground"/>\n' + welds + "\n"
            + carry_welds + "  </equality>\n</mujoco>\n")
    spec = mujoco.MjSpec.from_string(text)
    robots.attach(spec, "scout", pos=(2.0, -1.6, 0.0), yaw=90, prefix="scout/")
    robots.attach(spec, "responder", pos=(2.0, -2.8, 0.05), yaw=90, prefix="")
    m = spec.compile()
    force, torque = calibrate(m)
    out = spec.to_xml()
    custom = ('  <custom>\n    <numeric name="weld_limit" data="' + " ".join(f"{v:.0f}" for v in force) + '"/>\n'
              '    <numeric name="weld_torque_limit" data="' + " ".join(f"{v:.0f}" for v in torque) + '"/>\n')
    out = out.replace("  <custom>\n", custom, 1)
    header = ("<!--\n  AFTERSHOCK true-scale building after an earthquake (ref Y1b). GENERATED by\n"
              "  python -m sim.scenes.make_building: edit that, not this. SIM_SCENE=building.\n-->\n")
    return header + out


def calibrate(m):
    """(force, torque) breaking limits from each weld's static load after settling, in eq order."""
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    for _ in range(round(WARMUP_S / m.opt.timestep)):          # what World does before arming the breaker
        mujoco.mj_step(m, d)
    f0, t0 = np.zeros(m.neq), np.zeros(m.neq)
    for _ in range(round(2.0 / m.opt.timestep)):               # then the peak load at rest, not one sample
        mujoco.mj_step(m, d)
        f, t = breakage.weld_loads(m, d)
        f0, t0 = np.maximum(f0, f), np.maximum(t0, t)
    force, torque = np.zeros(m.neq), np.zeros(m.neq)
    for i in range(m.neq):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_EQUALITY, i) or ""
        if not name.startswith("j"):
            continue                                   # plate weld, robot internals: never break
        a, c = m.eq_obj1id[i], m.eq_obj2id[i]
        k = WEAK if (m.body_dofnum[a] > 0 or m.body_dofnum[c] > 0) else SOUND   # live pieces are cracked
        force[i] = max(k * f0[i], FLOOR_N)
        torque[i] = max(k * t0[i], FLOOR_NM)
    return force, torque


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", default=str(OUT))
    p.add_argument("--cache", help="pickle of the main-shock result: reused if it exists, written if not")
    a = p.parse_args()
    cache = pathlib.Path(a.cache) if a.cache else None
    if cache and cache.exists():
        b, keep, alive, voids = pickle.loads(cache.read_bytes())
    else:
        b, keep, alive, voids = build(a.seed)
        if cache:
            cache.write_bytes(pickle.dumps((b, keep, alive, voids)))
    text = final_xml(b, keep, alive, voids)
    pathlib.Path(a.out).write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {a.out}: {len(keep)} pieces, {len(alive)} welds, {1 + len(voids)} casualties")


if __name__ == "__main__":
    main()

_ = aftershock   # the in-demo aftershock is sim/aftershock.py; imported so the generator documents the link
