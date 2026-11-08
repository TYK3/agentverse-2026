"""Build the console's marker models (ref A1, CASUALTY-MODEL): a casualty figure and the levels scene's rubble,
both sized and posed from sim/scenes/levels.xml so the console never draws them bigger or elsewhere than the
simulator has them.

    python3 sim/assets/fetch.py            # the concrete textures, shared with build_glb.py
    uv run --no-project --python 3.11 --with bpy --with mujoco python sim/assets/build_markers.py

Writes, in the scene frame (metres, z up, NOT converted to glTF's y up), next to aftershock.glb:

  casualty.glb   "casualty": a template, NOT a position. The console clones it at each map/casualties pos
                 (perception's estimate), so the file never says where people are. Origin on the floor under
                 the centre of the body, lying on its back, head towards +x, inside the envelope of the
                 levels.xml casualty capsule: 2 * (half-length + radius) long, at most 2 * radius wide and high
                 (narrowed, not shortened, because the capsule is slimmer than an adult of its length).
                 One child mesh "casualty_body". extras: envelope_m [L, W, H], head "+x".
  debris.glb     "levels_debris": the rubble geoms of levels.xml (b20_rubble .. b23_rubble), one node per
                 id ("b20" .. "b23", like aftershock.glb's tower blocks), origin at the geom's centre and
                 posed where levels.xml has it. These are sim truth, like world/debris (never perception).
                 Each is a small pile of chunks pushed inwards from its box, so the model never shows rubble
                 where the simulator has free space. extras: label "rubble", half_m (MuJoCo half-extents).
"""

import importlib.util
import json
import math
import pathlib
import random

import mujoco

# isort: off
import bpy  # the bpy wheel only makes bmesh and mathutils importable after bpy itself
import bmesh
from mathutils import Matrix, Vector
# isort: on

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LEVELS = ROOT / "sim" / "scenes" / "levels.xml"
CASUALTY_GLB_NAME = "casualty.glb"
DEBRIS_GLB_NAME = "debris.glb"
SEGMENTS = 12            # limbs are ~1 cm on screen: few sides keep the console fast in software WebGL


def _module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


glb = _module("build_glb")   # shared materials, meshes and export


# ---------------------------------------------------------------- levels.xml

def levels_model():
    m = mujoco.MjModel.from_xml_path(str(LEVELS))
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    return m, d


def casualty_envelope(m):
    """(L, W, H) of the casualty capsules in levels.xml; every casualty has the same one."""
    sizes = set()
    for g in range(m.ngeom):
        body = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, int(m.geom_bodyid[g])) or ""
        if body.startswith("casualty_") and m.geom_type[g] == mujoco.mjtGeom.mjGEOM_CAPSULE:
            r, half = (round(float(v), 4) for v in m.geom_size[g][:2])
            sizes.add((r, half))
    if len(sizes) != 1:
        raise SystemExit(f"expected one casualty capsule size in {LEVELS.name}, found {sorted(sizes)}")
    r, half = sizes.pop()
    return [round(2 * (half + r), 4), round(2 * r, 4), round(2 * r, 4)]


def rubble_geoms(m, d):
    """[(id, half, pos, xmat)] for the levels.xml geoms named b<number>_rubble."""
    out = []
    for g in range(m.ngeom):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or ""
        bid, _, label = name.partition("_")
        if label == "rubble" and bid[:1] == "b" and bid[1:].isdigit():
            out.append((bid, [float(v) for v in m.geom_size[g]], d.geom_xpos[g].copy(), d.geom_xmat[g].copy()))
    return sorted(out, key=lambda r: int(r[0][1:]))


# ---------------------------------------------------------------- the casualty

def limb(p0, p1, r, squash=1.0):
    """A capsule from p0 to p1 (radius r; y scaled by `squash` in its own frame) as a world-space bmesh."""
    p0, p1 = Vector(p0), Vector(p1)
    axis = p1 - p0
    length = axis.length
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=False, segments=SEGMENTS, radius1=r, radius2=r, depth=length)
    for z in (-length / 2, length / 2):
        ball = bmesh.ops.create_uvsphere(bm, u_segments=SEGMENTS, v_segments=6, radius=r)
        bmesh.ops.translate(bm, vec=Vector((0, 0, z)), verts=ball["verts"])
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.scale(bm, vec=Vector((1, squash, 1)), verts=bm.verts)
    rot = Vector((0, 0, 1)).rotation_difference(axis.normalized()).to_matrix().to_4x4()
    bm.transform(Matrix.Translation((p0 + p1) / 2) @ rot)
    return bm


def ball(c, radii):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=SEGMENTS, v_segments=8, radius=1.0)
    bmesh.ops.scale(bm, vec=Vector(radii), verts=bm.verts)
    bmesh.ops.translate(bm, vec=Vector(c), verts=bm.verts)
    return bm


def figure(length):
    """Parts of a person lying on their back, head to +x, feet to -x, on z = 0, `length` metres long:
    [(part, bmesh, material key)]. Proportions are an adult's (head ~1/8 of the height); one knee is
    drawn up, as people trapped on their back often lie, so it reads as a person and not a log."""
    k = length / 1.75                  # an adult is ~1.75 m: everything below is in adult metres x k
    half = length / 2
    head_r = 0.11 * k
    x_head = half - head_r
    hip = -half + 0.92 * k             # adult landmark heights from the soles: hips 0.92 m, shoulders 1.45 m
    shoulder = -half + 1.45 * k
    parts = []
    # head and neck
    parts.append(("head", ball((x_head, 0, head_r), (head_r, head_r * 0.85, head_r)), "skin"))
    parts.append(("neck", limb((shoulder + 0.02 * k, 0, 0.09 * k), (x_head - head_r * 0.6, 0, head_r * 0.9),
                               0.05 * k), "skin"))
    # torso: chest to hips, flattened (wide, not deep)
    torso_r = 0.11 * k
    parts.append(("torso", limb((hip + 0.06 * k, 0, torso_r), (shoulder - 0.02 * k, 0, torso_r), torso_r, 1.6),
                  "shirt"))
    parts.append(("pelvis", ball((hip, 0, 0.10 * k), (0.12 * k, 0.17 * k, 0.10 * k)), "trousers"))
    # arms at the sides, hands by the hips
    for side in (-1, 1):
        y = side * 0.25 * k               # outside the torso (0.18 k half-width) plus the arm
        elbow = (shoulder - 0.30 * k, y * 1.05, 0.05 * k)
        parts.append((f"upper_arm_{side}", limb((shoulder - 0.03 * k, y, 0.07 * k), elbow, 0.045 * k), "shirt"))
        hand = (hip - 0.10 * k, y * 1.08, 0.04 * k)
        parts.append((f"forearm_{side}", limb(elbow, hand, 0.038 * k), "skin"))
    # legs: left straight, right knee up
    foot_x = -half + 0.05 * k
    for side, knee_up in ((1, False), (-1, True)):
        y = side * 0.10 * k
        top = (hip - 0.04 * k, y, 0.08 * k)
        thigh_r, shin_r = 0.07 * k, 0.05 * k
        if knee_up:
            knee = (hip - 0.40 * k, y, 0.30 * k)
            ankle = (foot_x + 0.14 * k, y, shin_r)
        else:
            knee = (hip - 0.45 * k, y, thigh_r * 0.9)
            ankle = (foot_x + 0.04 * k, y, shin_r)
        parts.append((f"thigh_{side}", limb(top, knee, thigh_r), "trousers"))
        parts.append((f"shin_{side}", limb(knee, ankle, shin_r), "trousers"))
        # the foot: toes up when the leg is straight, flat on the floor when the knee is drawn up
        if knee_up:
            foot = limb((ankle[0] + 0.01 * k, y, 0.035 * k), (ankle[0] - 0.16 * k, y, 0.035 * k), 0.035 * k, 1.2)
        else:
            foot = limb((ankle[0], y, shin_r), (ankle[0] - 0.02 * k, y, shin_r + 0.16 * k), 0.035 * k, 1.2)
        parts.append((f"foot_{side}", foot, "shoes"))
    return parts


def casualty(envelope):
    mats = {
        "skin": glb.flat("casualty_skin", (0.74, 0.55, 0.43, 1), roughness=0.7),
        "shirt": glb.flat("casualty_shirt", (0.22, 0.33, 0.52, 1), roughness=0.9),
        "trousers": glb.flat("casualty_trousers", (0.24, 0.23, 0.22, 1), roughness=0.9),
        "shoes": glb.flat("casualty_shoes", (0.10, 0.09, 0.08, 1), roughness=0.8),
    }
    root = glb.empty("casualty")
    objs = []
    for name, bm, mat in figure(envelope[0]):
        me = bpy.data.meshes.new(f"casualty_{name}")
        bm.to_mesh(me)
        bm.free()
        me.materials.append(mats[mat])
        obj = bpy.data.objects.new(f"casualty_{name}", me)
        bpy.context.collection.objects.link(obj)
        objs.append(obj)
    body = glb.merged(objs, "casualty_body")
    for poly in body.data.polygons:
        poly.use_smooth = True
    body.parent = root
    body.matrix_parent_inverse = Matrix.Identity(4)
    bpy.context.view_layer.update()
    lo, hi = _bounds(body)
    # Fit the envelope: as long as the capsule the simulator uses, never wider or taller. The capsule is
    # slimmer than an adult of its length, so the figure is narrowed (y) rather than shortened.
    sx = envelope[0] / (hi.x - lo.x)
    sy = min(sx, envelope[1] / (hi.y - lo.y))
    sz = min(sx, envelope[2] / (hi.z - lo.z))
    centre = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    body.data.transform(Matrix.Diagonal((sx, sy, sz, 1)) @ Matrix.Translation(-centre))
    body.data.update()
    bpy.context.view_layer.update()
    lo, hi = _bounds(body)
    root["envelope_m"] = envelope
    root["head"] = "+x"
    return {"size_m": [round(v, 3) for v in hi - lo], "faces": len(body.data.polygons)}


def _bounds(obj):
    pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    return (Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))),
            Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))))


# ---------------------------------------------------------------- the rubble

def rubble(geoms):
    # flat, not the tower's textured concrete: four small piles are not worth 2 MB of textures
    mat = glb.flat("debris_rubble", (0.55, 0.51, 0.47, 1), roughness=0.95)
    root = glb.empty("levels_debris")
    report = {}
    for bid, half, pos, xmat in geoms:
        rng = random.Random(int(bid[1:]))
        chunks = []
        n = 6
        for k in range(n):
            # every chunk stays inside the geom's box: half-extents and offsets are bounded by it
            ch = [half[0] * rng.uniform(0.25, 0.5), half[1] * rng.uniform(0.25, 0.5), half[2] * rng.uniform(0.35, 0.6)]
            cx = rng.uniform(-(half[0] - ch[0]), half[0] - ch[0])
            cy = rng.uniform(-(half[1] - ch[1]), half[1] - ch[1])
            cz = -half[2] + ch[2] if k < n - 2 else -half[2] + ch[2] + rng.uniform(0, half[2] * 2 - 2 * ch[2])
            bm = glb.box_mesh(f"{bid}_chunk", ch, cuts=2)
            glb.roughen(bm, ch, 0.5, int(bid[1:]) * 10 + k)
            yaw = rng.uniform(-0.5, 0.5)
            # a yawed chunk's corners reach further: shrink it until its rotated footprint fits again
            c, s_ = abs(math.cos(yaw)), abs(math.sin(yaw))
            reach = (ch[0] * c + ch[1] * s_, ch[0] * s_ + ch[1] * c)
            shrink = min(1.0, (half[0] - abs(cx)) / reach[0], (half[1] - abs(cy)) / reach[1])
            bmesh.ops.scale(bm, vec=Vector((shrink, shrink, 1)), verts=bm.verts)
            mw = Matrix.Translation((cx, cy, cz)) @ Matrix.Rotation(yaw, 4, "Z")
            chunks.append(glb.to_object(f"{bid}_chunk_{k}", bm, mat, mw, None))
        obj = glb.merged(chunks, bid)
        obj.data.transform(obj.matrix_world)            # mesh in the geom's own frame, origin at its centre
        obj.matrix_world = glb.pose_matrix(pos, xmat)
        obj.parent = root
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj["label"] = "rubble"
        half_m = [round(v, 4) for v in half]
        obj["half_m"] = half_m
        report[bid] = {"pos": [round(float(v), 4) for v in pos], "half_m": half_m}
    return report


# ---------------------------------------------------------------- main

def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    m, d = levels_model()
    report = {"casualty": casualty(casualty_envelope(m)), "debris": rubble(rubble_geoms(m, d))}
    report["casualty"]["envelope_m"] = casualty_envelope(m)
    out = {}
    for name, roots in ((CASUALTY_GLB_NAME, ["casualty"]), (DEBRIS_GLB_NAME, ["levels_debris"])):
        path = glb.OUT_DIR / name
        glb.export(path, roots)
        out[name] = round(path.stat().st_size / 1e6, 3)
    report["glb_mb"] = out
    print(json.dumps(report))


if __name__ == "__main__":
    build()
