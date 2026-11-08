"""A1 checks: the tower's basements and stair/lift core add collision without changing the robots' world,
and the console's demo model ships with every tower block named by its scene id."""

import json
import pathlib
import struct

import mujoco
import numpy as np
import pytest

from sim import aftershock, scene
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
    assert {"building", "annex"} <= names
    assert {"annex_body", "ground", "rebar"} <= names                 # static extras, merged
    robot_names = {n.get("name") for n in _glb_json(robots)["nodes"]}
    assert {"scout", "responder", "first_aid_kit"} <= robot_names
    assert not robot_names & blocks and not names & {"scout", "responder", "first_aid_kit"}   # split, not copied
    for n in names | robot_names:                                     # casualties are perception's job
        assert not (n and n.startswith(("casualty", "c1", "c2", "c3", "c4"))), n


def test_credits_ship_with_the_model_and_need_no_attribution_gaps():
    credits = json.loads((MODELS / "CREDITS.json").read_text())
    assert credits == fetch.CREDITS
    for c in credits:
        assert c["licence"] in ("CC0", "CC-BY-4.0", "BSD-3-Clause") and c["author"] and c["source"].startswith("https://")
    assert (MODELS / "parking_garage_1k.hdr").read_bytes()[:10] == b"#?RADIANCE"


# ---------------------------------------------------------------- ASSET-LOD: the software-GL tower

def test_lite_tower_matches_the_full_one_without_textures():
    """aftershock_lite.glb (sim/assets/build_lod.py) must stay in step with aftershock.glb: same nodes, poses,
    extras and geometry, flat materials. Re-run build_lod.py after build_glb.py if this fails."""
    full, lite = _glb_json(MODELS / "aftershock.glb"), _glb_json(MODELS / "aftershock_lite.glb")
    keys = ("name", "translation", "rotation", "scale", "matrix", "children", "mesh", "extras")
    assert [{k: n.get(k) for k in keys} for n in lite["nodes"]] == [{k: n.get(k) for k in keys} for n in full["nodes"]]
    assert lite["scenes"] == full["scenes"]
    assert not lite.get("images") and not lite.get("textures")
    for mf, ml in zip(full["meshes"], lite["meshes"], strict=True):
        for pf, pl in zip(mf["primitives"], ml["primitives"], strict=True):
            assert set(pl["attributes"]) == {"POSITION", "NORMAL"} and pl["material"] == pf["material"]
            for attr in ("POSITION", "NORMAL"):
                af, al = full["accessors"][pf["attributes"][attr]], lite["accessors"][pl["attributes"][attr]]
                assert (al["count"], al.get("min"), al.get("max")) == (af["count"], af.get("min"), af.get("max"))
            assert lite["accessors"][pl["indices"]]["count"] == full["accessors"][pf["indices"]]["count"]
    assert [m["name"] for m in lite["materials"]] == [m["name"] for m in full["materials"]]
    for m in lite["materials"]:
        assert set(m) <= {"name", "doubleSided", "pbrMetallicRoughness", "alphaMode", "extras"}, m["name"]
        assert all(0 < c <= 1 for c in m["pbrMetallicRoughness"]["baseColorFactor"])
    assert (MODELS / "aftershock_lite.glb").stat().st_size < 0.35 * (MODELS / "aftershock.glb").stat().st_size
