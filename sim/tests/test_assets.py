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


# ---------------------------------------------------------------- CASUALTY-MODEL: marker models

LEVELS = ROOT / "sim" / "scenes" / "levels.xml"


def _glb(path):
    """(json, nodes by name) of a GLB."""
    j = _glb_json(path)
    return j, {n.get("name"): n for n in j["nodes"]}


def _mesh_bounds(j, node):
    """Axis-aligned bounds of a node's mesh in the node's own frame (from the POSITION accessors)."""
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for prim in j["meshes"][node["mesh"]]["primitives"]:
        acc = j["accessors"][prim["attributes"]["POSITION"]]
        lo, hi = np.minimum(lo, acc["min"]), np.maximum(hi, acc["max"])
    return lo, hi


def _levels():
    m = mujoco.MjModel.from_xml_path(str(LEVELS))
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    return m, d


def test_casualty_model_is_a_template_inside_the_sims_casualty_capsule():
    j, nodes = _glb(MODELS / "casualty.glb")
    root, body = nodes["casualty"], nodes["casualty_body"]
    # a template, not a position: perception's map/casualties says where people are
    assert root.get("translation", [0, 0, 0]) == [0, 0, 0] and "matrix" not in root
    assert root["children"] == [j["nodes"].index(body)]
    assert body.get("translation", [0, 0, 0]) == [0, 0, 0] and "rotation" not in body and "scale" not in body
    m, _ = _levels()
    caps = [m.geom_size[g][:2] for g in range(m.ngeom)
            if (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, int(m.geom_bodyid[g])) or "").startswith("casualty_")]
    assert len(caps) == 3 and all(np.allclose(c, caps[0]) for c in caps)
    r, half = (float(v) for v in caps[0])
    envelope = [2 * (half + r), 2 * r, 2 * r]
    assert root["extras"]["envelope_m"] == pytest.approx(envelope) and root["extras"]["head"] == "+x"
    lo, hi = _mesh_bounds(j, body)
    assert hi[0] - lo[0] == pytest.approx(envelope[0], abs=1e-3)       # as long as the sim's casualty
    assert hi[1] - lo[1] <= envelope[1] + 1e-4 and hi[2] - lo[2] <= envelope[2] + 1e-4
    assert lo[2] == pytest.approx(0, abs=1e-4)                           # lies on the floor at pos z
    assert (lo[:2] + hi[:2]) / 2 == pytest.approx([0, 0], abs=1e-3)     # origin under the centre


def test_debris_model_has_each_levels_rubble_geom_where_the_sim_has_it():
    j, nodes = _glb(MODELS / "debris.glb")
    m, d = _levels()
    rubble = {}
    for g in range(m.ngeom):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or ""
        if name.endswith("_rubble"):
            rubble[name.split("_")[0]] = (d.geom_xpos[g].copy(), m.geom_size[g].copy(), d.geom_xmat[g].reshape(3, 3))
    assert sorted(rubble) == ["b20", "b21", "b22", "b23"]
    root = nodes["levels_debris"]
    assert sorted(j["nodes"][i]["name"] for i in root["children"]) == sorted(rubble)
    for bid, (pos, half, xmat) in rubble.items():
        node = nodes[bid]
        assert np.allclose(xmat, np.eye(3))                              # levels rubble is axis-aligned
        assert node["translation"] == pytest.approx(list(pos), abs=1e-5)
        assert node["extras"] == {"label": "rubble", "half_m": pytest.approx(list(half), abs=1e-4)}
        lo, hi = _mesh_bounds(j, node)
        assert np.all(lo >= -half - 1e-4) and np.all(hi <= half + 1e-4), bid   # never outside its sim box
        assert lo[2] == pytest.approx(-half[2], abs=0.05 * half[2])         # resting on the floor (roughened)


def test_marker_models_are_small():
    assert (MODELS / "casualty.glb").stat().st_size + (MODELS / "debris.glb").stat().st_size < 0.5e6
