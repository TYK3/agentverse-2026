"""A1 checks: the tower's basements and stair/lift core add collision without changing the robots' world,
and the console's demo model ships with every tower block named by its scene id."""

import json
import pathlib
import struct

import mujoco
import numpy as np
import pytest

from sim import aftershock, robots, scene
from sim.assets import annex, fetch
from sim.world import World

ROOT = pathlib.Path(__file__).resolve().parents[2]
MODELS = ROOT / "console" / "public" / "models"
LOOSE = ["b26", "b27"]               # as in test_tower.py: the two loose slabs


def test_generated_annex_scene_is_up_to_date(tmp_path):
    out = annex.write_scene(out=tmp_path / "tower_annex.xml")
    assert annex.OUT.read_text() == out.read_text(), "run python3 sim/assets/annex.py"


def test_annex_never_enters_the_robots_world():
    """Below the floor plate, or west of the tower's west wall: never the ground storey or the yard."""
    boxes = annex.boxes()
    assert len(boxes) > 50
    assert [b[0] for b in boxes if not annex.footprint_clear(b)] == []


def test_annex_scene_loads_and_adds_no_contacts_or_mass():
    plain, with_annex = scene.load(scene.TOWER), scene.load(annex.OUT)
    plate = "plate"
    assert with_annex[0].ngeom == plain[0].ngeom + len(annex.boxes())
    assert with_annex[0].body(plate).mass[0] == pytest.approx(plain[0].body(plate).mass[0])
    for m, d in (plain, with_annex):
        for _ in range(round(1.0 / m.opt.timestep)):
            mujoco.mj_step(m, d)
    assert with_annex[1].ncon == plain[1].ncon                 # nothing rests on or rubs the annex
    for (m, d) in (plain, with_annex):
        assert [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i) for i in scene.block_ids(m)] == \
            [f"b{k}" for k in range(1, 28)]
    settled = [d.xpos[scene.block_ids(m)] for m, d in (plain, with_annex)]
    assert np.allclose(settled[0], settled[1], atol=1e-6)


def test_aftershock_is_unchanged_with_the_annex():
    m, d = scene.load(annex.OUT)
    moved, _ = aftershock.aftershock_effects(m, d)
    assert sorted(aftershock.body_name(m, i) for i in moved) == LOOSE
    w = World(path=annex.OUT, render=False)
    w.trigger_aftershock()
    events = []
    for _ in range(31):
        events += w.tick(0.1)
    assert events == [("world/change", {"kind": "aftershock", "t": 3.0, "moved_blocks": LOOSE})]


def _glb_json(path):
    data = path.read_bytes()
    assert data[:4] == b"glTF"
    n = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + n])


def test_console_model_has_every_block_and_part_and_fits_the_budget():
    tower, robots = MODELS / "aftershock.glb", MODELS / "robots.glb"
    assert tower.stat().st_size + robots.stat().st_size < 20e6
    names = {n.get("name") for n in _glb_json(tower)["nodes"]}
    m, _ = scene.load(scene.TOWER)
    blocks = {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i) for i in scene.block_ids(m)}
    assert blocks <= names, sorted(blocks - names)
    assert {"building", "annex", "B1", "B2", "B3", "core"} <= names
    assert {"B1_body", "B2_body", "B3_body", "core_body", "ground", "rebar"} <= names   # merged meshes
    robot_names = {n.get("name") for n in _glb_json(robots)["nodes"]}
    assert {"scout", "responder", "first_aid_kit"} <= robot_names
    assert not robot_names & blocks and not names & {"scout", "responder", "first_aid_kit"}   # split, not copied
    for n in names | robot_names:                                     # casualties are perception's job
        assert not (n and n.startswith(("casualty", "c1", "c2", "c3", "c4"))), n


def _mesh_bounds(path, node_name):
    """Axis-aligned (low, high) of a node's mesh from the GLB's POSITION accessor bounds (node unposed)."""
    gltf = _glb_json(path)
    node = next(n for n in gltf["nodes"] if n.get("name") == node_name)
    assert not any(k in node for k in ("translation", "rotation", "scale", "matrix")), node   # mesh in robot frame
    prims = gltf["meshes"][node["mesh"]]["primitives"]
    lo = np.min([gltf["accessors"][p["attributes"]["POSITION"]]["min"] for p in prims], axis=0)
    hi = np.max([gltf["accessors"][p["attributes"]["POSITION"]]["max"] for p in prims], axis=0)
    return lo, hi


@pytest.mark.parametrize("name", ["scout", "responder"])
def test_robot_models_are_the_agreed_true_scale_robots(name):
    """LIMO Pro and Jackal envelopes (docs/hardware.md), from the sim's own MJCF: no stand-in model."""
    lo, hi = _mesh_bounds(MODELS / "robots.glb", f"{name}_body")
    length, width = robots.SPEC[name]["size"][:2]
    assert hi[0] - lo[0] == pytest.approx(length, abs=0.005)
    assert hi[1] - lo[1] == pytest.approx(width, abs=0.005)
    assert lo[2] == pytest.approx(0.0, abs=1e-3)                       # wheels on the ground
    assert abs(lo[0] + hi[0]) < 0.01 and abs(lo[1] + hi[1]) < 0.01      # origin under the base centre
    m, d = robots.load(name)                                            # same geoms, Responder arm stowed
    mlo, mhi = robots.extent(m, d, f"{name}/{name}")
    assert np.allclose(lo, mlo, atol=0.01) and np.allclose(hi, mhi, atol=0.01)


@pytest.mark.parametrize("level,floor_z", [("B1", -1.0), ("B2", -2.0), ("B3", -3.0)])
def test_basement_levels_are_separate_nodes_in_a_fixed_frame(level, floor_z):
    """Each basement level is its own node at (0, 0, floor z), z up, scale 1, holding exactly the annex
    boxes (cut at the level boundaries) from its floor slab up to the underside of the slab above."""
    gltf = _glb_json(MODELS / "aftershock.glb")
    nodes = gltf["nodes"]
    annex_node = next(n for n in nodes if n.get("name") == "annex")
    node = next(n for n in nodes if n.get("name") == level)
    assert nodes.index(node) in annex_node["children"]
    assert node["translation"] == [0, 0, floor_z]
    assert "rotation" not in node and "scale" not in node and "matrix" not in node
    assert node["extras"]["level"] == level and node["extras"]["floor_z"] == floor_z
    assert [nodes[c]["name"] for c in node["children"]] == [f"{level}_body"]
    lo, hi = _mesh_bounds(MODELS / "aftershock.glb", f"{level}_body")
    zlo, zhi = floor_z - 2 * annex.T, floor_z + 1 - 2 * annex.T
    inside = [(b_lo, b_hi) for _, _, b_lo, b_hi in annex.boxes() if b_hi[2] > zlo and b_lo[2] < zhi]
    want_lo = np.min([b[0] for b in inside], axis=0)
    want_hi = np.max([b[1] for b in inside], axis=0)
    assert np.allclose(lo[:2], want_lo[:2], atol=1e-3) and np.allclose(hi[:2], want_hi[:2], atol=1e-3)
    assert lo[2] == pytest.approx(zlo - floor_z, abs=1e-3) and hi[2] == pytest.approx(zhi - floor_z, abs=1e-3)


def test_credits_ship_with_the_model_and_need_no_attribution_gaps():
    credits = json.loads((MODELS / "CREDITS.json").read_text())
    assert credits == fetch.CREDITS
    for c in credits:
        assert c["licence"] in ("CC0", "CC-BY-4.0", "BSD-3-Clause") and c["author"] and c["source"].startswith("https://")
    assert (MODELS / "parking_garage_1k.hdr").read_bytes()[:10] == b"#?RADIANCE"
