"""Build the console's demo models (ref A1): one GLB with the tower, its basements and core, and a small one
with the robots and the first aid kit, from the free assets fetched by sim/assets/fetch.py.

    python3 sim/assets/fetch.py
    uv run --no-project --python 3.11 --with bpy --with mujoco python sim/assets/build_glb.py [--preview out.png]

Writes console/public/models/aftershock.glb (tower) and robots.glb (scene frame: metres, z up, NOT
converted to glTF's y up), the HDRI next to them and CREDITS.json. They are separate files so the console
only parses the tower (the slow one in software GL) when the tower scene is shown. Headless Blender (the bpy wheel) does the modelling and export.

Nodes, so the console can find them by name (aftershock.glb: building, annex; robots.glb: the rest):
  building/      b1..b27, one mesh per tower block, named by its block id (scene/loaded "id") and posed
                 as in tower.xml; "rebar" (rods out of the broken slab edges) and "ground" (with the
                 excavation pit) are visual extras, each merged into one mesh
  annex/B1, B2, B3  the basement levels from sim/assets/annex.py (same boxes as the MuJoCo collision
                 scene sim/scenes/tower_annex.xml, cut at the level boundaries) plus visual debris on B1
                 and in the pit. Each is its own node: z up, metres, scale 1, no rotation, origin
                 (0, 0, floor z) with floor z -1, -2, -3 (extras: level, floor_z), holding one mesh
                 "<level>_body" in that frame (one draw call per material, not ~150)
  annex/core     the stair/lift core above the ground floor, one mesh "core_body"
  scout          the AgileX LIMO Pro, built from sim/robots/scout.xml's geoms: true scale, the agreed
                 322 x 220 mm envelope (docs/hardware.md), wheels, LiDAR, cameras and mic array where the
                 spec puts them
  responder      the Clearpath Jackal with its mast, sensors and Gen3 lite arm, built from
                 sim/robots/responder.xml's geoms with the arm stowed (sim.robots.load): true scale,
                 the agreed 508 x 430 mm envelope
  first_aid_kit  Quaternius First Aid Kit, fitted to the scene's kit box
Robot and kit origins are on the ground under their centre, facing +x, like the sim's mocap bodies. The
robots are the same geoms the simulator uses, so the console never shows a different robot (no stand-in
legged or toy model); the console scales them to the footprint it draws.
Casualties are NOT in the model: where people are is what perception has to find.

Ground-storey geometry stays inside its MuJoCo boxes: rubble and broken edges are only ever pushed
inwards, so the model never shows an obstacle where the simulator has free space.
"""

import argparse
import importlib.util
import json
import math
import pathlib
import random
import shutil
import sys

import mujoco
import numpy as np

# isort: off
import bpy  # the bpy wheel only makes bmesh and mathutils importable after bpy itself
import bmesh
from mathutils import Matrix, Vector, noise
# isort: on

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = HERE / "cache"
TOWER = ROOT / "sim" / "scenes" / "tower.xml"
OUT_DIR = ROOT / "console" / "public" / "models"
GLB = OUT_DIR / "aftershock.glb"
ROBOTS_GLB = OUT_DIR / "robots.glb"
UV_TILE_M = 0.75         # one texture repeat per 0.75 m: brick courses in proportion to 0.3 m robots
SATURATION = 0.25        # the Poly Haven texture is red-painted; keep a trace of the paint, mostly grey
MAX_MB = 20.0
ROUND_SEGMENTS = 20      # cylinder and capsule sides: robots are ~0.2 m on screen
ROBOT_FACES = 4000       # per merged robot: ~0.2 m on screen, so ~30k triangles halved the frame rate


def _module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


annex = _module("annex")
fetch = _module("fetch")
sys.path.insert(0, str(ROOT))
from sim import robots as sim_robots  # the true-scale MJCF robots, arm stow and extent

# ---------------------------------------------------------------- materials

def concrete(name, tint, rough_scale=1.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    diff = nt.nodes.new("ShaderNodeTexImage")
    diff.image = _image("concrete_diff_1k.jpg", "sRGB")
    tint_node = nt.nodes.new("ShaderNodeMix")
    tint_node.data_type = "RGBA"
    tint_node.blend_type = "MULTIPLY"
    tint_node.inputs["Factor"].default_value = 1.0
    tint_node.inputs[7].default_value = (*tint, 1.0)          # B colour input
    nt.links.new(diff.outputs["Color"], tint_node.inputs[6])  # A colour input
    nt.links.new(tint_node.outputs[2], bsdf.inputs["Base Color"])
    rough = nt.nodes.new("ShaderNodeTexImage")
    rough.image = _image("concrete_rough_1k.jpg", "Non-Color")
    nt.links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])
    nor = nt.nodes.new("ShaderNodeTexImage")
    nor.image = _image("concrete_nor_gl_1k.jpg", "Non-Color")
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nmap.inputs["Strength"].default_value = rough_scale
    nt.links.new(nor.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def flat(name, rgba, metallic=0.0, roughness=0.6):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


_images = {}


def _image(fname, colorspace):
    if fname not in _images:
        path = CACHE / fname
        if fname == "concrete_diff_1k.jpg":
            path = _desaturated(path)
        img = bpy.data.images.load(str(path))
        img.colorspace_settings.name = colorspace
        _images[fname] = img
    return _images[fname]


def _desaturated(src):
    """A grey copy of the diffuse texture (baked, because glTF cannot carry Blender's colour nodes)."""
    out = src.with_name(src.stem + "_grey.jpg")
    img = bpy.data.images.load(str(src))
    px = np.empty(len(img.pixels), dtype=np.float32)
    img.pixels.foreach_get(px)
    rgba = px.reshape(-1, 4)
    lum = rgba[:, :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    rgba[:, :3] = lum[:, None] + (rgba[:, :3] - lum[:, None]) * SATURATION
    img.pixels.foreach_set(rgba.ravel())
    img.filepath_raw = str(out)
    img.file_format = "JPEG"
    img.save()
    bpy.data.images.remove(img)
    return out


# ---------------------------------------------------------------- meshes

def box_mesh(name, half, cuts=0):
    """A box mesh centred on the origin with half-extents `half`, optionally subdivided."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * half[0], v.co.y * half[1], v.co.z * half[2]))
    if cuts:
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
    return bm


def roughen(bm, half, depth, seed):
    """Push vertices inwards by up to `depth` x the smallest half-extent: a chunk, never larger than its box."""
    m = min(half) * depth
    off = Vector((seed * 1.7, seed * 3.1, seed * 0.7))
    for v in bm.verts:
        n = noise.noise(v.co * 9.0 + off) * 0.5 + 0.5
        inward = Vector((-v.co.x / half[0], -v.co.y / half[1], -v.co.z / half[2]))
        v.co += Vector((inward.x * half[0], inward.y * half[1], inward.z * half[2])).normalized() * (m * n)


def break_face(bm, half, axis, sign, depth, seed):
    """Jag one face: its vertices move inwards (along -axis) by a noisy amount up to `depth` metres."""
    i = "xyz".index(axis)
    rng = random.Random(seed)
    for v in bm.verts:
        if abs(v.co[i] - sign * half[i]) < 1e-6:
            n = noise.noise(v.co * 6.0 + Vector((seed, 0, 0))) * 0.5 + 0.5
            v.co[i] -= sign * depth * (0.35 + 0.65 * n) * rng.uniform(0.7, 1.0)


def to_object(name, bm, mat, matrix, parent):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    obj.matrix_world = matrix
    obj.parent = parent
    obj.matrix_parent_inverse = Matrix.Identity(4)
    if mat:
        me.materials.append(mat)
        box_uv(obj)
    return obj


def box_uv(obj):
    """World-space box mapping: each face takes the two world axes across its normal, so textures keep
    their real size on every block whatever its scale or rotation."""
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    uv = bm.loops.layers.uv.new("UVMap")
    mw = obj.matrix_world
    rot = mw.to_3x3()
    for f in bm.faces:
        n = rot @ f.normal
        a = max(range(3), key=lambda k: abs(n[k]))
        u, w = [k for k in range(3) if k != a]
        for loop in f.loops:
            p = mw @ loop.vert.co
            loop[uv].uv = (p[u] / UV_TILE_M, p[w] / UV_TILE_M)
    bm.to_mesh(me)
    bm.free()


def empty(name, parent=None):
    e = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(e)
    e.parent = parent
    return e


def pose_matrix(pos, xmat):
    r = np.asarray(xmat).reshape(3, 3)
    m = Matrix(((r[0, 0], r[0, 1], r[0, 2], pos[0]),
                (r[1, 0], r[1, 1], r[1, 2], pos[1]),
                (r[2, 0], r[2, 1], r[2, 2], pos[2]),
                (0, 0, 0, 1)))
    return m


# ---------------------------------------------------------------- the tower

BROKEN = {                 # block id: (axis, side, depth m) of the broken face (inwards only)
    "b9": ("x", 1, 0.10),      # F1 ledge over the collapsed east room
    "b14": ("x", 1, 0.08),     # F2 east edge
    "b15": ("z", 1, 0.25),     # broken storey-3 west wall
    "b16": ("z", 1, 0.25),     # broken storey-3 north wall
    "b13": ("z", 1, 0.12),     # storey-2 east wall, cracked top
    "b17": ("x", -1, 0.06),    # lean-to slab, sheared end
    "b23": ("y", 1, 0.06),     # pancake slab
}


def tower(mats, root):
    m = mujoco.MjModel.from_xml_path(str(TOWER))
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    out = {}
    for b in range(m.nbody):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, b) or ""
        if not (name.startswith("b") and name[1:].isdigit()):
            continue
        g = m.body_geomadr[b]
        gname = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or ""
        label = gname.split("_", 1)[1] if "_" in gname else "block"
        half = [float(v) for v in m.geom_size[g]]
        seed = int(name[1:])
        if label == "rubble":
            bm = box_mesh(name, half, cuts=4)
            roughen(bm, half, 0.45, seed)
        elif name in BROKEN:
            axis, side, depth = BROKEN[name]
            bm = box_mesh(name, half, cuts=8)
            break_face(bm, half, axis, side, min(depth, 1.6 * half["xyz".index(axis)]), seed)
        else:
            bm = box_mesh(name, half)
        mat = mats.get(label, mats["wall"])
        obj = to_object(name, bm, mat, pose_matrix(d.geom_xpos[g], d.geom_xmat[g]), root)
        obj["label"] = label
        out[name] = (obj, half, d.geom_xpos[g].copy())
    return out


def rebar(blocks, mat, root):
    """Rods sticking out of the broken slab edges (visual only, 6 mm, drooping)."""
    rng = random.Random(7)
    k = 0
    for bid in ("b9", "b14"):
        _obj, half, pos = blocks[bid]
        x_edge = pos[0] + half[0] - 0.04
        for y in np.arange(pos[1] - half[1] + 0.12, pos[1] + half[1] - 0.1, 0.22):
            length = rng.uniform(0.08, 0.26)
            droop = rng.uniform(5, 35)
            z = pos[2] + rng.uniform(-0.6, 0.6) * half[2]
            bm = bmesh.new()
            bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=0.006, radius2=0.006, depth=length)
            bmesh.ops.translate(bm, verts=bm.verts, vec=Vector((0, 0, length / 2)))
            mw = (Matrix.Translation((x_edge, float(y), z))
                  @ Matrix.Rotation(math.radians(90 + droop), 4, "Y"))
            to_object(f"rebar_{k}", bm, mat, mw, root)
            k += 1


def ground(mat, root):
    """The ground around the tower with the excavation pit east of it and a hole over the core."""
    z0, z1 = -0.1, 0.0
    pieces = [  # (lo, hi) in x/y; the pit is x 2.05..3.2, y -1.55..1.55; the core is x -2.95..-2.05
        ((-4.5, -4.5), (4.5, -1.65)),
        ((-4.5, 1.65), (4.5, 4.5)),
        ((-4.5, -1.65), (-2.95, 1.65)),
        ((-2.05, -1.65), (2.05, 1.65)),
        ((3.3, -1.65), (4.5, 1.65)),
        ((-2.95, -1.65), (-2.05, -1.55)),
        ((-2.95, 1.55), (-2.05, 1.65)),
        ((2.05, -1.65), (3.3, -1.55)),
        ((2.05, 1.55), (3.3, 1.65)),
    ]
    for i, (lo, hi) in enumerate(pieces):
        half = [(hi[0] - lo[0]) / 2, (hi[1] - lo[1]) / 2, (z1 - z0) / 2]
        c = ((hi[0] + lo[0]) / 2, (hi[1] + lo[1]) / 2, (z1 + z0) / 2)
        to_object(f"ground_{i}", box_mesh("g", half), mat, Matrix.Translation(c), root)


# Basement levels: each owns its floor slab and everything up to the underside of the slab above, so the
# three nodes stack without overlap. Origin of each node: its floor top under the tower centre.
LEVELS = {"B1": -1.0, "B2": -2.0, "B3": -3.0}
SLAB_T = 2 * annex.T


def level_range(floor_z):
    return floor_z - SLAB_T, floor_z + 1.0 - SLAB_T


def clip_z(lo, hi, zlo, zhi):
    """The part of box (lo, hi) between zlo and zhi, or None."""
    a, b = max(lo[2], zlo), min(hi[2], zhi)
    return ((lo[0], lo[1], a), (hi[0], hi[1], b)) if b - a > 1e-6 else None


def build_annex(mats, root):
    """annex/{B1,B2,B3,core}: the annex boxes cut at the level boundaries, so each basement level is one
    addressable node (z up, metres, scale 1, origin (0, 0, floor z)); "core" is the stair/lift core above
    the ground floor. Visual only: sim/assets/annex.py's MuJoCo boxes are not cut."""
    parts = {}
    for lvl, z in LEVELS.items():
        e = empty(lvl, root)
        e.location = (0.0, 0.0, z)
        e["level"], e["floor_z"], e["frame"] = lvl, z, "scene frame: metres, z up"
        parts[lvl] = (e, *level_range(z))
    core = empty("core", root)
    parts["core"] = (core, level_range(LEVELS["B1"])[1], math.inf)
    bpy.context.view_layer.update()

    def place(name, bm, mat, world, lvl):
        obj = to_object(name, bm, mat, world, None)       # world-space UVs first, then into the level
        e = parts[lvl][0]
        obj.parent = e
        obj.matrix_parent_inverse = e.matrix_world.inverted()

    for name, label, lo, hi in annex.boxes():
        mat = mats["lift"] if label == "lift" else mats["slab"] if label in ("slab", "stair") else mats["wall"]
        for lvl, (_, zlo, zhi) in parts.items():
            cut = clip_z(lo, hi, zlo, zhi)
            if cut is None:
                continue
            half = [(b - a) / 2 for a, b in zip(*cut, strict=True)]
            c = [(a + b) / 2 for a, b in zip(*cut, strict=True)]
            place(f"{name}@{lvl}", box_mesh(name, half), mat, Matrix.Translation(c), lvl)
    rng = random.Random(11)
    piles = [("B1", (0.5, -1.3, -1.0), (1.9, 1.3, -1.0), 28),     # B1 under the collapsed east room
             ("B3", (2.2, -1.4, -3.0), (3.1, 1.4, -3.0), 14)]     # spoil in the pit
    k = 0
    for lvl, lo, hi, n in piles:
        for _ in range(n):
            half = [rng.uniform(0.04, 0.16), rng.uniform(0.04, 0.12), rng.uniform(0.03, 0.08)]
            bm = box_mesh("d", half, cuts=2)
            roughen(bm, half, 0.5, k + 100)
            c = (rng.uniform(lo[0], hi[0]), rng.uniform(lo[1], hi[1]), lo[2] + half[2] * 0.8)
            mw = Matrix.Translation(c) @ Matrix.Rotation(rng.uniform(0, math.pi), 4, "Z") \
                @ Matrix.Rotation(rng.uniform(-0.4, 0.4), 4, "X")
            place(f"debris_{k}", bm, mats["rubble"], mw, lvl)
            k += 1
    for lvl, (e, _, _) in parts.items():
        merge_children(e, "", f"{lvl}_body")
        body = e.children[0]
        body.data.transform(body.matrix_basis)            # vertices in the level frame, body node unposed
        body.matrix_basis = Matrix.Identity(4)


# ---------------------------------------------------------------- robots and kit

def footprint(name):
    """Half-extents of a geom in the tower scene (the robots' chassis boxes and the kit)."""
    m = mujoco.MjModel.from_xml_path(str(TOWER))
    return [float(v) for v in m.geom_size[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, name)]]


def merged(objs, name):
    """Apply modifiers and join `objs` into one mesh: one draw call per material instead of one per part
    (a dozen parts per robot cost the console more frame time than the whole tower in software WebGL)."""
    bpy.context.view_layer.update()
    for o in objs:
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
        for mod in list(o.modifiers):
            with bpy.context.temp_override(object=o, active_object=o):
                bpy.ops.object.modifier_apply(modifier=mod.name)
    if len(objs) > 1:
        with bpy.context.temp_override(active_object=objs[0], selected_editable_objects=objs, selected_objects=objs):
            bpy.ops.object.join()
    objs[0].name = name
    return objs[0]


def merge_children(root, prefix, name):
    kids = [o for o in root.children if o.type == "MESH" and o.name.startswith(prefix)]
    if kids:
        obj = merged(kids, name)
        mw = obj.matrix_world.copy()
        obj.parent = root
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_world = mw


def fit(root, objs, half, *, keep_height=False):
    """Uniformly scale and move `objs` (already posed in world space) so their xy bounds fit inside the
    box `half`, centred, standing on z 0; then join them into one mesh parented to `root` at the origin."""
    objs = [merged(objs, f"{root.name}_body")]
    faces = len(objs[0].data.polygons)
    if faces > ROBOT_FACES:                 # small on screen: keep the console fast in software WebGL
        dec = objs[0].modifiers.new("decimate", "DECIMATE")
        dec.ratio = ROBOT_FACES / faces
        with bpy.context.temp_override(object=objs[0], active_object=objs[0]):
            bpy.ops.object.modifier_apply(modifier=dec.name)
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    size = hi - lo
    s = min(2 * half[0] / size.x, 2 * half[1] / size.y)
    if not keep_height:
        s = min(s, 2 * half[2] / size.z) if len(half) > 2 and half[2] > 0 else s
    centre = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    mw = Matrix.Diagonal((s, s, s, 1)) @ Matrix.Translation(-centre)
    for o in objs:
        o.matrix_world = mw @ o.matrix_world
        o.parent = root
        o.matrix_parent_inverse = Matrix.Identity(4)
    return s, size * s


def _geom_mesh(t, size, bevel):
    """A bmesh for one MuJoCo box, cylinder or capsule, in the geom's own frame."""
    bm = bmesh.new()
    if t == sim_robots.BOX:
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=Vector([2 * v for v in size]), verts=bm.verts)
        r = min(bevel, 0.4 * min(size))
        if r > 0.002:
            bmesh.ops.bevel(bm, geom=bm.edges[:], offset=r, segments=1, affect="EDGES")
    elif t == sim_robots.CYLINDER:
        bmesh.ops.create_cone(bm, cap_ends=True, segments=ROUND_SEGMENTS, radius1=size[0], radius2=size[0],
                              depth=2 * size[1])
    elif t == sim_robots.CAPSULE:
        bmesh.ops.create_cone(bm, cap_ends=False, segments=ROUND_SEGMENTS, radius1=size[0], radius2=size[0],
                              depth=2 * size[1])
        for z in (-size[1], size[1]):
            ball = bmesh.ops.create_uvsphere(bm, u_segments=ROUND_SEGMENTS, v_segments=8, radius=size[0])
            bmesh.ops.translate(bm, vec=Vector((0, 0, z)), verts=ball["verts"])
    else:
        bm.free()
        return None
    return bm


def mjcf_robot(root, name, bevel=0.006):
    """The robot's own MJCF geoms (sim/robots/<name>.xml, Responder arm stowed) as one true-scale mesh under
    `root`, origin on the ground under the base centre, facing +x. Returns (L, W, H) in metres."""
    m, d = sim_robots.load(name)
    mats, objs = {}, []
    for g in range(m.ngeom):
        bm = _geom_mesh(int(m.geom_type[g]), [float(v) for v in m.geom_size[g]], bevel)
        if bm is None:
            continue                                       # the floor plane
        rgba = tuple(float(c) for c in m.geom_rgba[g])
        key = tuple(round(c, 2) for c in rgba)
        if key not in mats:
            metal = 0.5 if key[:3] in ((0.5, 0.5, 0.5), (0.4, 0.4, 0.45), (0.85, 0.85, 0.85)) else 0.1
            mats[key] = flat(f"{name}_{len(mats)}", rgba, metallic=metal, roughness=0.5)
        me = bpy.data.meshes.new(f"{name}_{g}")
        bm.to_mesh(me)
        bm.free()
        me.materials.append(mats[key])
        obj = bpy.data.objects.new(f"{name}_part_{g}", me)
        bpy.context.collection.objects.link(obj)
        obj.matrix_world = pose_matrix(d.geom_xpos[g], d.geom_xmat[g])
        objs.append(obj)
    body = merged(objs, f"{name}_body")
    body.data.transform(body.matrix_world)                 # bake the pose: the mesh is in the robot frame
    body.matrix_world = Matrix.Identity(4)
    body.parent = root
    body.matrix_parent_inverse = Matrix.Identity(4)
    lo, hi = sim_robots.extent(m, d, f"{name}/{name}")
    return [round(float(v), 3) for v in hi - lo]


def imported(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    new = [o for o in bpy.data.objects if o not in before]
    for o in new:                                 # glTF import adds a y-up -> z-up rotation on the roots
        if o.parent is None:
            o.matrix_world = o.matrix_world
    return [o for o in new if o.type == "MESH"], [o for o in new if o.type != "MESH"]


def placed(root, path, half, yaw_deg=0.0, keep_height=True):
    meshes, others = imported(path)
    bpy.context.view_layer.update()
    for o in meshes:
        o.matrix_world = Matrix.Rotation(math.radians(yaw_deg), 4, "Z") @ o.matrix_world.copy()
        o.parent = None
    bpy.context.view_layer.update()
    for o in others:
        bpy.data.objects.remove(o)
    return fit(root, meshes, half, keep_height=keep_height)


# ---------------------------------------------------------------- main

def build(preview=None, kit_yaw=0.0):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = {
        "wall": concrete("wall", (0.92, 0.86, 0.76)),
        "slab": concrete("slab", (0.78, 0.78, 0.8)),
        "rubble": concrete("rubble", (0.62, 0.57, 0.52), 1.5),
        "ground": concrete("ground", (0.55, 0.55, 0.56), 0.6),
        "lift": flat("lift", (0.45, 0.48, 0.52, 1), metallic=0.8, roughness=0.35),
        "rebar": flat("rebar", (0.35, 0.22, 0.15, 1), metallic=0.7, roughness=0.6),
    }
    building = empty("building")
    blocks = tower(mats, building)
    rebar(blocks, mats["rebar"], building)
    ground(mats["ground"], building)
    annex_root = empty("annex")
    build_annex(mats, annex_root)
    # Static extras become one mesh each (one draw call per material); the blocks stay one mesh per id.
    merge_children(building, "rebar_", "rebar")
    merge_children(building, "ground_", "ground")
    report = {"blocks": sorted(blocks, key=lambda b: int(b[1:]))}
    report["scout"] = {"size_m": mjcf_robot(empty("scout"), "scout")}
    report["responder"] = {"size_m": mjcf_robot(empty("responder"), "responder")}
    s, size = placed(empty("first_aid_kit"), CACHE / "first_aid_kit.glb", footprint("first_aid_kit_supply"),
                     kit_yaw, keep_height=False)
    report["first_aid_kit"] = {"scale": round(s, 4), "size_m": [round(v, 3) for v in size]}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    export(GLB, ["building", "annex"])
    export(ROBOTS_GLB, ["scout", "responder", "first_aid_kit"])
    shutil.copyfile(CACHE / "parking_garage_1k.hdr", OUT_DIR / "parking_garage_1k.hdr")
    (OUT_DIR / "CREDITS.json").write_text(json.dumps(fetch.CREDITS, indent=2) + "\n")
    mb = (GLB.stat().st_size + ROBOTS_GLB.stat().st_size) / 1e6
    report["glb_mb"] = {"tower": round(GLB.stat().st_size / 1e6, 2), "robots": round(ROBOTS_GLB.stat().st_size / 1e6, 2)}
    print(json.dumps(report))
    if mb > MAX_MB:
        raise SystemExit(f"the models are {mb:.1f} MB, over the {MAX_MB} MB budget")
    if preview:
        render(preview)


def export(path, roots):
    """Export the named root empties and everything under them to one GLB."""
    bpy.ops.object.select_all(action="DESELECT")
    for name in roots:
        root = bpy.data.objects[name]
        for o in [root, *root.children_recursive]:
            o.select_set(True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", export_yup=False, export_apply=True,
                              export_image_format="AUTO", export_extras=True, export_cameras=False,
                              export_lights=False, use_selection=True)


def render(path):
    scene = bpy.context.scene
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    scene.collection.objects.link(cam)
    cam.location = (7.5, -8.0, 6.5)
    cam.rotation_euler = (Vector((0.0, 0.0, -0.8)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.rotation_euler = (0.7, 0.2, 0.8)
    scene.collection.objects.link(sun)
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "TEXTURE"
    scene.render.resolution_x, scene.render.resolution_y = 1280, 800
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", help="also render a PNG preview to this path")
    ap.add_argument("--kit-yaw", type=float, default=0.0)
    args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
    build(args.preview, args.kit_yaw)
