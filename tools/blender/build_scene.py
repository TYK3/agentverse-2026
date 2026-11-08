"""BLENDER-LOOK: build the AFTERLIGHT console models in Blender, headless, and export small GLBs.

    blender -b --factory-startup -P tools/blender/build_scene.py              # writes console/public/models/
    blender -b --factory-startup -P tools/blender/build_scene.py -- --blend /tmp/afterlight.blend

Writes:
  console/public/models/blender_tower.glb       collapsed 4 x 3 m tower: ground, L1, L2 (from sim/scenes/tower.xml,
                                                same boxes, ids and poses) + basements B1..B3 (proposed spec)
  console/public/models/blender_scout.glb       Scout (LIMO-class), 0.33 x 0.23 x 0.29 m
  console/public/models/blender_responder.glb   Responder (Jackal-class), 0.52 x 0.44 x 0.75 m incl. mast
  console/public/models/blender_manifest.json   dimensions, node names, triangle counts, file sizes

Units: metres, Z up, +X east / robot forward, ground finished floor z = 0. The glTF exporter converts to
+Y up (Blender's default), so the console rotates the loaded scene once by +90 degrees about X.

The above-ground tower is read from the MJCF, never re-typed: every b<N> body with a box geom becomes a mesh
of the same size, pose and id. Welded ("braced") blocks are merged per level and material so the GLB stays at
a handful of draw calls; free blocks (loose slabs, light rubble) stay separate nodes named by body id.
Basements follow the AFTERLIGHT scene spec (slab tops -1/-2/-3 m, 0.10 m slabs and walls, 0.90 m headroom,
0.80 x 0.85 m east portal). They are illustrative: sim/scenes has no basement under the tower yet.
Decorative rubble is seeded (SEED) and kept off the spec's clear corridor (y -0.40..0.40) and turn pad.
Robots are procedural silhouettes at the full spec envelopes (an approximation, not a vendor mesh);
ground contact at z = 0, +X forward, root nodes "scout" / "responder".
"""

import json
import math
import random
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
TOWER_XML = ROOT / "sim" / "scenes" / "tower.xml"
OUT = ROOT / "console" / "public" / "models"
SEED = 8112026
TEX = 256                       # texture edge, px: small on purpose (GLB budget)

SCOUT_DIMS = (0.33, 0.23, 0.29)
RESPONDER_DIMS = (0.52, 0.44, 0.75)
SLAB = 0.10
BASEMENT_TOPS = {"b1": -1.0, "b2": -2.0, "b3": -3.0}
HEADROOM = 0.90
CORE = (-2.0, 2.0, -1.5, 1.5)
CORRIDOR_Y = (-0.40, 0.40)
TURN_PAD = (0.75, 1.75, -0.5, 0.5)
PORTAL_Y, PORTAL_H = (-0.40, 0.40), 0.85
STAIR_Y = (0.55, 1.35)


def args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    blend = a[a.index("--blend") + 1] if "--blend" in a else None
    return blend


# ---------------------------------------------------------------------------------------------- textures
def noise(n, octaves, rng, scale0=8):
    """Tileable value noise in 0..1, n x n."""
    out = np.zeros((n, n), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        k = scale0 * (2 ** o)
        grid = rng.random((k, k)).astype(np.float32)
        xs = np.arange(n) * k / n
        i0 = np.floor(xs).astype(int) % k
        i1 = (i0 + 1) % k
        f = xs - np.floor(xs)
        f = f * f * (3 - 2 * f)
        a = grid[i0][:, i0] * (1 - f)[None, :] + grid[i0][:, i1] * f[None, :]
        b = grid[i1][:, i0] * (1 - f)[None, :] + grid[i1][:, i1] * f[None, :]
        out += amp * (a * (1 - f)[:, None] + b * f[:, None])
        total += amp
        amp *= 0.5
    return out / total


def save_image(name, rgb):
    n = rgb.shape[0]
    img = bpy.data.images.new(name, n, n, alpha=False)
    rgba = np.ones((n, n, 4), np.float32)
    rgba[..., :3] = np.clip(rgb, 0, 1)
    img.pixels.foreach_set(rgba.ravel())
    path = Path(bpy.app.tempdir) / f"{name}.jpg"
    img.filepath_raw = str(path)
    img.file_format = "JPEG"
    bpy.context.scene.render.image_settings.quality = 82
    img.save()
    img.source = "FILE"
    img.filepath = str(path)
    img.reload()
    return img


def srgb(hexstr):
    h = hexstr.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]


def concrete_textures():
    rng = np.random.default_rng(SEED)
    base = noise(TEX, 6, rng)
    stain = noise(TEX, 3, rng, scale0=2)
    pores = (rng.random((TEX, TEX)) > 0.985).astype(np.float32)
    height = base * 0.8 + 0.2 * noise(TEX, 2, rng, scale0=32) - 0.5 * pores
    gy, gx = np.gradient(height)
    nrm = np.stack([-gx * 6, -gy * 6, np.ones_like(gx)], -1)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    normal_img = save_image("concrete_normal", nrm * 0.5 + 0.5)
    albedo = {}
    for name, hexc in (("concrete", "#77766e"), ("aggregate", "#57564f"), ("slab", "#6d6c66")):
        col = np.array([int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)], np.float32)
        shade = 0.78 + 0.32 * base - 0.18 * stain - 0.35 * pores
        rgb = col[None, None, :] * shade[..., None]
        rgb[..., 0] += 0.025 * stain                          # warm dust in the stains
        albedo[name] = save_image(f"{name}_albedo", rgb)
    return albedo, normal_img


# --------------------------------------------------------------------------------------------- materials
MATS = {}


def material(name, color=None, rough=0.9, metal=0.0, image=None, normal=None, emit=None, emit_strength=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    if image is not None:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = image
        nt.links.new(t.outputs["Color"], p.inputs["Base Color"])
    else:
        p.inputs["Base Color"].default_value = (*srgb(color), 1)
    if normal is not None:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = normal
        t.image.colorspace_settings.name = "Non-Color"
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.inputs["Strength"].default_value = 0.8
        nt.links.new(t.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], p.inputs["Normal"])
    if emit:
        p.inputs["Emission Color"].default_value = (*srgb(emit), 1)
        p.inputs["Emission Strength"].default_value = emit_strength
    MATS[name] = m
    return m


def make_materials():
    albedo, nrm = concrete_textures()
    material("concrete_wall", image=albedo["concrete"], normal=nrm, rough=0.90)
    material("concrete_slab", image=albedo["slab"], normal=nrm, rough=0.92)
    material("broken_aggregate", image=albedo["aggregate"], normal=nrm, rough=0.96)
    material("rust_steel", "#704832", rough=0.80, metal=0.65)
    material("hazard_amber", "#e8a43b", rough=0.55, emit="#e8a43b", emit_strength=0.6)
    material("safety_black", "#1d2327", rough=0.70)
    material("rubber", "#15181b", rough=0.95)
    material("ivory", "#efe8d6", rough=0.50)
    material("scout_blue", "#4a6c8f", rough=0.45, metal=0.15)
    material("responder_orange", "#e06a1e", rough=0.45, metal=0.10)
    material("anodised_grey", "#9aa3ab", rough=0.35, metal=0.80)
    material("lens", "#0b1118", rough=0.10, metal=0.30)
    material("headlight", "#fff4e0", rough=0.20, emit="#fff1d6", emit_strength=4.0)
    material("status_green", "#3ddc84", rough=0.30, emit="#3ddc84", emit_strength=3.0)
    material("kit_red", "#c8322f", rough=0.60)


# --------------------------------------------------------------------------------------------- geometry
class Builder:
    """Collects triangles/quads in object space; one mesh per Builder, one material slot per name."""

    def __init__(self, uv_scale=0.6):
        self.v, self.f, self.mat, self.uv = [], [], [], []
        self.mats = []
        self.uv_scale = uv_scale

    def add_bm(self, bm, matrix, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        mi = self.mats.index(mat)
        base = len(self.v)
        nmat = matrix.to_3x3()
        for v in bm.verts:
            self.v.append(tuple(matrix @ v.co))
        for face in bm.faces:
            self.f.append([base + v.index for v in face.verts])
            self.mat.append(mi)
            n = (nmat @ face.normal).normalized()
            ax = max(range(3), key=lambda i: abs(n[i]))
            u, w = [(1, 2), (0, 2), (0, 1)][ax]
            self.uv.append([(self.v[base + v.index][u] / self.uv_scale, self.v[base + v.index][w] / self.uv_scale)
                            for v in face.verts])
        bm.free()

    def object(self, name, parent=None):
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.v, [], self.f)
        uvl = me.uv_layers.new(name="UVMap")
        for poly, uvs in zip(me.polygons, self.uv):
            for li, uv in zip(poly.loop_indices, uvs):
                uvl.data[li].uv = uv
        for m in self.mats:
            me.materials.append(MATS[m])
        for poly, mi in zip(me.polygons, self.mat):
            poly.material_index = mi
        me.validate()
        ob = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(ob)
        if parent is not None:
            ob.parent = parent
        return ob


def box_bm(sx, sy, sz, bevel=0.008):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts)
    if bevel and min(sx, sy, sz) > 3 * bevel:
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=bevel, segments=1, affect="EDGES", profile=0.5)
    bm.verts.index_update()
    bm.faces.ensure_lookup_table()
    return bm


def cyl_bm(r, h, seg=16, r2=None):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r if r2 is None else r2, depth=h)
    bm.verts.index_update()
    return bm


def chunk_bm(rng, sx, sy, sz):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=0.5)
    for v in bm.verts:
        v.co *= 0.75 + 0.5 * rng.random()
        v.co.z = max(v.co.z, -0.3)                 # flattened underside so it sits on the slab
    bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts)
    bm.verts.index_update()
    return bm


def T(x, y, z, rx=0.0, ry=0.0, rz=0.0):
    return Matrix.Translation((x, y, z)) @ Euler((rx, ry, rz), "XYZ").to_matrix().to_4x4()


def box_between(b, lo, hi, mat, bevel=0.008):
    c = [(a + z) / 2 for a, z in zip(lo, hi)]
    s = [z - a for a, z in zip(lo, hi)]
    b.add_bm(box_bm(*s, bevel=bevel), T(*c), mat)


# ----------------------------------------------------------------------------------------- tower (MJCF)
def mj_rot(euler_deg):
    """MuJoCo default eulerseq 'xyz' (intrinsic, degrees) as a rotation matrix."""
    ax, ay, az = (math.radians(float(v)) for v in euler_deg.split())
    return (Matrix.Rotation(ax, 4, "X") @ Matrix.Rotation(ay, 4, "Y") @ Matrix.Rotation(az, 4, "Z"))


def tower_blocks():
    root = ET.parse(TOWER_XML).getroot()
    world = root.find("worldbody")
    braced = {w.get("body1") for w in root.iter("weld") if w.get("body2") == "plate"}
    out = []
    for body in world.findall("body"):
        name = body.get("name", "")
        geom = body.find("geom")
        if name[:1] != "b" or not name[1:].isdigit() or geom is None or geom.get("type") != "box":
            continue
        pos = [float(v) for v in body.get("pos").split()]
        size = [2 * float(v) for v in geom.get("size").split()]        # MJCF half extents -> full
        rot = mj_rot(body.get("euler")) if body.get("euler") else Matrix.Identity(4)
        label = geom.get("name").split("_", 1)[1]
        out.append({"name": name, "label": label, "pos": pos, "size": size, "rot": rot, "braced": name in braced})
    return out


def level_of(z):
    return "level_g" if z < 1.0 else ("level_l1" if z < 2.1 else "level_l2")


def build_tower():
    rng = random.Random(SEED)
    root = bpy.data.objects.new("tower", None)
    bpy.context.scene.collection.objects.link(root)
    report = {"blocks": [], "levels": {}}
    groups = {}
    for blk in tower_blocks():
        lvl = level_of(blk["pos"][2])
        mat = {"wall": "concrete_wall", "slab": "concrete_slab"}.get(blk["label"], "broken_aggregate")
        m = Matrix.Translation(blk["pos"]) @ blk["rot"]
        if blk["braced"]:
            b = groups.setdefault(lvl, Builder())
            b.add_bm(box_bm(*blk["size"]), m, mat)
        else:                                            # free body: own node, origin at the body frame
            b = Builder()
            b.add_bm(box_bm(*blk["size"]), blk["rot"], mat)
            ob = b.object(blk["name"], root)
            ob.location = blk["pos"]
        report["blocks"].append({"id": blk["name"], "label": blk["label"], "level": lvl, "braced": blk["braced"],
                                 "pos": blk["pos"], "size": [round(s, 4) for s in blk["size"]]})

    # Ground storey slab (finished floor z = 0), the core footprint only: the sim's 9 x 9 m plate would seal
    # the basements from view.
    g = groups.setdefault("level_g", Builder())
    box_between(g, (CORE[0] - 0.05, CORE[2] - 0.05, -SLAB), (CORE[1] + 0.05, CORE[3] + 0.05, 0.0), "concrete_slab")

    # Rebar sticking out of the broken F1 ledge (x = 0.9) and the storey-2 east face; never over a route.
    rb = groups.setdefault("level_l1", Builder())
    for i in range(14):
        y = -1.4 + i * 0.2 + rng.uniform(-0.04, 0.04)
        length = rng.uniform(0.08, 0.25)
        droop = rng.uniform(-0.6, 0.1)
        rb.add_bm(cyl_bm(0.004, length, seg=6), T(0.9 + length / 2 * math.cos(droop), y, 1.152 + length / 2 * math.sin(droop),
                                                  0, math.pi / 2 - droop, 0), "rust_steel")

    # Ground-floor debris: small fragments along the wall bases of the collapsed east room, under 0.04 m tall.
    dbg = groups.setdefault("level_g", Builder())
    for _ in range(90):
        side = rng.choice(("n", "e", "s", "w"))
        x = {"n": rng.uniform(0.5, 1.9), "s": rng.uniform(0.5, 1.9), "e": rng.uniform(1.8, 1.92),
             "w": rng.uniform(0.48, 0.6)}[side]
        y = {"n": rng.uniform(1.3, 1.42), "s": rng.uniform(-1.42, -1.3), "e": rng.uniform(-1.4, 1.4),
             "w": rng.uniform(-1.4, 1.4)}[side]
        s = rng.uniform(0.012, 0.05)
        dbg.add_bm(chunk_bm(rng, s, s * rng.uniform(0.6, 1.2), s * rng.uniform(0.4, 0.8)),
                   T(x, y, s * 0.15, rz=rng.uniform(0, 6.28)), "broken_aggregate")

    for lvl, b in groups.items():
        b.object(f"{lvl}_static", root)
    build_basements(root, rng, report)
    return root, report


def build_basements(root, rng, report):
    x0, x1, y0, y1 = CORE
    density = {"b1": 1.0, "b2": 1.25, "b3": 1.5}
    for lvl, top in BASEMENT_TOPS.items():
        b = Builder()
        south = Builder()
        ceil = top + HEADROOM
        box_between(b, (x0 - 0.05, y0 - 0.05, top - SLAB), (x1 + 0.05, y1 + 0.05, top), "concrete_slab")
        # west wall with the 0.80 m stair connection (y 0.55..1.35, 0.85 m high)
        box_between(b, (x0, y0, top), (x0 + 0.1, STAIR_Y[0], ceil), "concrete_wall")
        box_between(b, (x0, STAIR_Y[1], top), (x0 + 0.1, y1, ceil), "concrete_wall")
        box_between(b, (x0, STAIR_Y[0], top + PORTAL_H), (x0 + 0.1, STAIR_Y[1], ceil), "concrete_wall")
        # east wall with the 0.80 x 0.85 m service portal (y -0.40..0.40)
        box_between(b, (x1 - 0.1, y0, top), (x1, PORTAL_Y[0], ceil), "concrete_wall")
        box_between(b, (x1 - 0.1, PORTAL_Y[1], top), (x1, y1, ceil), "concrete_wall")
        box_between(b, (x1 - 0.1, PORTAL_Y[0], top + PORTAL_H), (x1, PORTAL_Y[1], ceil), "concrete_wall")
        box_between(b, (x1 - 0.1, PORTAL_Y[0] - 0.03, top), (x1 + 0.02, PORTAL_Y[0], top + PORTAL_H), "hazard_amber", 0)
        box_between(b, (x1 - 0.1, PORTAL_Y[1], top), (x1 + 0.02, PORTAL_Y[1] + 0.03, top + PORTAL_H), "hazard_amber", 0)
        # north wall; the south wall is its own node so the console can cut it away
        box_between(b, (x0 + 0.1, y1 - 0.1, top), (x1 - 0.1, y1, ceil), "concrete_wall")
        box_between(south, (x0 + 0.1, y0, top), (x1 - 0.1, y0 + 0.1, ceil), "concrete_wall")
        # corner piers 0.15 x 0.15
        for px, py in ((x0 + 0.1, y0 + 0.1), (x1 - 0.25, y0 + 0.1), (x0 + 0.1, y1 - 0.25), (x1 - 0.25, y1 - 0.25)):
            box_between(b, (px, py, top), (px + 0.15, py + 0.15, ceil), "concrete_wall")
        # rubble in the spec's zones, never in the corridor (y -0.40..0.40) or on the turn pad
        n = int(26 * density[lvl])
        for zx0, zx1, zy0, zy1 in ((-1.8, -0.8, -1.3, -0.6), (0.3, 1.6, 0.65, 1.3)):
            for _ in range(n):
                x, y = rng.uniform(zx0, zx1), rng.uniform(zy0, zy1)
                if CORRIDOR_Y[0] - 0.05 < y < CORRIDOR_Y[1] + 0.05:
                    continue
                s = rng.uniform(0.04, 0.16)
                b.add_bm(chunk_bm(rng, s, s * rng.uniform(0.6, 1.3), s * rng.uniform(0.35, 0.7)),
                         T(x, y, top + s * 0.12, rz=rng.uniform(0, 6.28)), "broken_aggregate")
            for _ in range(n // 6):
                x, y = rng.uniform(zx0, zx1), rng.uniform(zy0, zy1)
                length = rng.uniform(0.08, 0.25)
                b.add_bm(cyl_bm(0.004, length, seg=6), T(x, y, top + 0.03, 0, math.pi / 2 - rng.uniform(0, 0.4),
                                                       rng.uniform(0, 6.28)), "rust_steel")
        # casualty pad outline (safe pad), amber, flush on the slab
        pad = {"b1": (-1.15, 0.80), "b2": (-1.15, 0.80), "b3": (-1.10, 0.75)}[lvl]
        for dx0, dy0, dx1, dy1 in ((-0.35, -0.20, 0.35, -0.18), (-0.35, 0.18, 0.35, 0.20),
                                   (-0.35, -0.18, -0.33, 0.18), (0.33, -0.18, 0.35, 0.18)):
            box_between(b, (pad[0] + dx0, pad[1] + dy0, top), (pad[0] + dx1, pad[1] + dy1, top + 0.004), "hazard_amber", 0)
        ob = b.object(f"level_{lvl}_static", root)
        so = south.object(f"level_{lvl}_wall_s", root)
        report["levels"][f"level_{lvl}"] = {"slab_top": top, "ceiling_underside": ceil, "illustrative": True}
        ob["illustrative"] = so["illustrative"] = True

    # B1 test slab (hazards_dynamic): pivot along X at y = 1.10, z = -0.65; initial tilt 12 degrees about X.
    pivot = bpy.data.objects.new("b1_test_slab_pivot", None)
    bpy.context.scene.collection.objects.link(pivot)
    pivot.parent = root
    pivot.location = (0.45, 1.10, -0.65)
    pivot.rotation_euler = (math.radians(-12), 0, 0)
    s = Builder()
    s.add_bm(box_bm(0.70, 0.50, 0.06, bevel=0.006), T(0, -0.25, 0), "concrete_slab")
    for i in range(5):
        s.add_bm(cyl_bm(0.004, 0.14, seg=6), T(-0.3 + i * 0.15, 0.03, 0, math.pi / 2, 0, 0), "rust_steel")
    so = s.object("b1_test_slab", pivot)
    so["presentation_only"] = True


# --------------------------------------------------------------------------------------------- robots
def wheel(b, x, y, r, w, hub_mat="anodised_grey"):
    b.add_bm(cyl_bm(r, w, seg=20), T(x, y, r, math.pi / 2, 0, 0), "rubber")
    b.add_bm(cyl_bm(r * 0.55, w, seg=12), T(x, y, r, math.pi / 2, 0, 0), hub_mat)


def build_scout():
    W = SCOUT_DIMS[1]
    root = bpy.data.objects.new("scout", None)
    bpy.context.scene.collection.objects.link(root)
    b = Builder()
    r, w = 0.055, 0.045
    for x in (-0.105, 0.105):
        for y in (-(W / 2 - w / 2), W / 2 - w / 2):
            wheel(b, x, y, r, w)
    box_between(b, (-0.155, -0.07, 0.045), (0.155, 0.07, 0.165), "scout_blue", 0.012)
    box_between(b, (-0.165, -0.07, 0.06), (0.165, 0.07, 0.10), "safety_black", 0.008)    # bumpers set L = 0.33
    box_between(b, (-0.12, -0.065, 0.165), (0.10, 0.065, 0.185), "ivory", 0.006)          # label deck
    box_between(b, (0.11, -0.04, 0.12), (0.155, 0.04, 0.16), "safety_black", 0.006)       # depth camera
    b.add_bm(cyl_bm(0.012, 0.01, seg=12), T(0.156, -0.022, 0.14, 0, math.pi / 2, 0), "lens")
    b.add_bm(cyl_bm(0.012, 0.01, seg=12), T(0.156, 0.022, 0.14, 0, math.pi / 2, 0), "lens")
    b.add_bm(cyl_bm(0.012, 0.03, seg=12), T(-0.02, 0, 0.215), "anodised_grey")             # lidar post
    b.add_bm(cyl_bm(0.036, 0.06, seg=20), T(-0.02, 0, 0.26), "safety_black")              # lidar, top z = 0.29
    b.add_bm(cyl_bm(0.037, 0.012, seg=20), T(-0.02, 0, 0.255), "lens")
    for y in (-0.05, 0.05):
        box_between(b, (0.161, y - 0.012, 0.075), (0.165, y + 0.012, 0.09), "headlight", 0)
    box_between(b, (-0.165, -0.05, 0.11), (-0.161, 0.05, 0.12), "status_green", 0)
    b.object("scout_body", root)
    return root


def build_responder():
    W = RESPONDER_DIMS[1]
    root = bpy.data.objects.new("responder", None)
    bpy.context.scene.collection.objects.link(root)
    b = Builder()
    r, w = 0.098, 0.065
    for x in (-0.13, 0.13):
        for y in (-(W / 2 - w / 2), W / 2 - w / 2):
            wheel(b, x, y, r, w, "safety_black")
    box_between(b, (-0.25, -0.155, 0.06), (0.25, 0.155, 0.22), "responder_orange", 0.02)
    box_between(b, (-0.26, -0.15, 0.07), (0.26, 0.15, 0.12), "safety_black", 0.01)        # bumpers set L = 0.52
    box_between(b, (-0.21, -0.14, 0.22), (0.21, 0.14, 0.24), "safety_black", 0.006)       # deck plate
    box_between(b, (-0.20, -0.14, 0.24), (-0.18, 0.14, 0.27), "anodised_grey", 0.004)     # payload rails
    box_between(b, (0.02, -0.14, 0.24), (0.04, 0.14, 0.27), "anodised_grey", 0.004)
    box_between(b, (-0.17, -0.09, 0.24), (-0.01, 0.01, 0.30), "kit_red", 0.006)           # first aid kit 0.16x0.10x0.06
    box_between(b, (-0.11, -0.03, 0.302), (-0.07, -0.026, 0.304), "ivory", 0)             # cross on the kit
    box_between(b, (-0.12, -0.045, 0.302), (-0.06, -0.011, 0.304), "ivory", 0)
    box_between(b, (-0.16, 0.05, 0.24), (-0.135, 0.10, 0.36), "safety_black", 0.004)      # radio 0.025x0.05x0.12
    b.add_bm(cyl_bm(0.003, 0.08, seg=6), T(-0.145, 0.09, 0.40), "safety_black")
    # sensor mast to 0.75 m: post, crossbar, camera, lidar puck, amber beacon
    box_between(b, (0.10, -0.02, 0.24), (0.14, 0.02, 0.62), "anodised_grey", 0.004)
    box_between(b, (0.08, -0.09, 0.58), (0.16, 0.09, 0.62), "anodised_grey", 0.004)
    box_between(b, (0.15, -0.06, 0.585), (0.19, 0.06, 0.615), "safety_black", 0.004)
    b.add_bm(cyl_bm(0.01, 0.01, seg=10), T(0.192, -0.035, 0.60, 0, math.pi / 2, 0), "lens")
    b.add_bm(cyl_bm(0.01, 0.01, seg=10), T(0.192, 0.035, 0.60, 0, math.pi / 2, 0), "lens")
    b.add_bm(cyl_bm(0.05, 0.07, seg=24), T(0.12, 0, 0.655), "safety_black")
    b.add_bm(cyl_bm(0.051, 0.014, seg=24), T(0.12, 0, 0.65), "lens")
    b.add_bm(cyl_bm(0.018, 0.04, seg=12), T(0.12, 0, 0.71), "hazard_amber")                # top z = 0.73
    b.add_bm(cyl_bm(0.008, 0.02, seg=8), T(0.12, 0, 0.74), "safety_black")                 # top z = 0.75
    for y in (-0.10, 0.10):
        box_between(b, (0.256, y - 0.025, 0.135), (0.26, y + 0.025, 0.16), "headlight", 0)
    box_between(b, (-0.12, -0.156, 0.15), (0.12, -0.154, 0.19), "ivory", 0)               # side labels
    box_between(b, (-0.12, 0.154, 0.15), (0.12, 0.156, 0.19), "ivory", 0)
    b.object("responder_body", root)
    return root


# --------------------------------------------------------------------------------------------- export
def select_tree(root):
    bpy.ops.object.select_all(action="DESELECT")
    for ob in [root, *root.children_recursive]:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = root


def export(root, path):
    select_tree(root)
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True, export_yup=True,
                              export_apply=True, export_extras=True, export_cameras=False, export_lights=False,
                              export_image_format="AUTO", export_draco_mesh_compression_enable=False)


def tris(root):
    n = 0
    for ob in [root, *root.children_recursive]:
        if ob.type == "MESH":
            n += sum(len(p.vertices) - 2 for p in ob.data.polygons)
    return n


def bbox(root):
    pts = [ob.matrix_world @ Vector(c) for ob in root.children_recursive if ob.type == "MESH" for c in ob.bound_box]
    lo = [round(min(p[i] for p in pts), 4) for i in range(3)]
    hi = [round(max(p[i] for p in pts), 4) for i in range(3)]
    return lo, hi


def main():
    blend = args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    make_materials()
    tower, report = build_tower()
    scout, responder = build_scout(), build_responder()
    bpy.context.view_layer.update()
    OUT.mkdir(parents=True, exist_ok=True)
    files = {"blender_tower.glb": tower, "blender_scout.glb": scout, "blender_responder.glb": responder}
    for fname, root in files.items():
        export(root, OUT / fname)
    try:
        commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    manifest = {
        "scene_version": 1,
        "source_commit": commit,
        "builder": "tools/blender/build_scene.py",
        "blender": bpy.app.version_string,
        "seed": SEED,
        "units": "metres, Z up in Blender; glTF +Y up (console rotates +90 deg about X once)",
        "sources": {"tower": "sim/scenes/tower.xml (boxes, ids, poses)",
                    "basements": "AFTERLIGHT scene spec section 2 (illustrative, not in the sim yet)"},
        "files": {},
        "tower": report,
        "robots": {"scout": {"envelope_spec": SCOUT_DIMS}, "responder": {"envelope_spec": RESPONDER_DIMS}},
    }
    for fname, root in files.items():
        lo, hi = bbox(root)
        manifest["files"][fname] = {"bytes": (OUT / fname).stat().st_size, "triangles": tris(root),
                                    "bbox_min": lo, "bbox_max": hi,
                                    "size": [round(h - l, 4) for l, h in zip(lo, hi)]}
    for key, root in (("scout", scout), ("responder", responder)):
        manifest["robots"][key]["envelope_built"] = manifest["files"][f"blender_{key}.glb"]["size"]
    (OUT / "blender_manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    for fname, info in manifest["files"].items():
        print(f"{fname:24} {info['bytes'] / 1024:7.1f} KB {info['triangles']:7d} tris  size {info['size']}")
    if blend:
        bpy.ops.wm.save_as_mainfile(filepath=blend)
        print(f"saved {blend}")


main()
