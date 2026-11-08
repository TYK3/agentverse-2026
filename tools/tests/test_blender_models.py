"""BLENDER-LOOK: the committed Blender GLBs match the spec envelopes and the sim's tower (no Blender needed)."""

import json
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "console" / "public" / "models"
MANIFEST = json.loads((MODELS / "blender_manifest.json").read_text(encoding="utf-8"))


def gltf_json(name):
    data = (MODELS / name).read_bytes()
    magic, version, _length = struct.unpack("<4sII", data[:12])
    assert magic == b"glTF" and version == 2
    size, kind = struct.unpack("<I4s", data[12:20])
    assert kind == b"JSON"
    return json.loads(data[20:20 + size])


def test_files_are_small_and_listed():
    for name, info in MANIFEST["files"].items():
        path = MODELS / name
        assert path.stat().st_size == info["bytes"]
        limit = 2_000_000 if name == "blender_tower.glb" else 300_000      # robots ~0.1 MB, tower ~1 MB
        assert info["bytes"] < limit, name


def test_robots_are_built_at_the_full_spec_envelopes():
    assert MANIFEST["robots"]["scout"]["envelope_built"] == [0.33, 0.23, 0.29]
    assert MANIFEST["robots"]["responder"]["envelope_built"] == [0.52, 0.44, 0.75]
    for key in ("scout", "responder"):
        info = MANIFEST["files"][f"blender_{key}.glb"]
        assert info["bbox_min"][2] == 0.0                                   # wheels on z = 0
        assert info["triangles"] <= 20_000
        names = [n.get("name") for n in gltf_json(f"blender_{key}.glb")["nodes"]]
        assert key in names


def test_tower_has_every_sim_block_with_its_id_and_size():
    world = ET.parse(ROOT / "sim" / "scenes" / "tower.xml").getroot().find("worldbody")
    sim = {}
    for body in world.findall("body"):
        name, geom = body.get("name", ""), body.find("geom")
        if name[:1] == "b" and name[1:].isdigit() and geom is not None and geom.get("type") == "box":
            sim[name] = [round(2 * float(v), 4) for v in geom.get("size").split()]
    built = {b["id"]: b for b in MANIFEST["tower"]["blocks"]}
    assert set(built) == set(sim)
    for name, size in sim.items():
        assert built[name]["size"] == size, name
    nodes = {n.get("name") for n in gltf_json("blender_tower.glb")["nodes"]}
    free = {b["id"] for b in MANIFEST["tower"]["blocks"] if not b["braced"]}
    assert free <= nodes                                                     # moving bodies stay their own nodes
    assert {"level_g_static", "level_l1_static", "level_b1_static", "level_b2_static", "level_b3_static"} <= nodes


def test_basements_follow_the_spec_levels():
    levels = MANIFEST["tower"]["levels"]
    assert [levels[f"level_b{i}"]["slab_top"] for i in (1, 2, 3)] == [-1.0, -2.0, -3.0]
    for i in (1, 2, 3):
        assert round(levels[f"level_b{i}"]["ceiling_underside"] - levels[f"level_b{i}"]["slab_top"], 6) == 0.9
        assert levels[f"level_b{i}"]["illustrative"] is True


def test_tower_textures_are_small():
    doc = gltf_json("blender_tower.glb")
    for img in doc.get("images", []):
        assert doc["bufferViews"][img["bufferView"]]["byteLength"] < 100_000
