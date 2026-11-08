"""Build the light tower model for software WebGL (ref A1, ASSET-LOD).

    uv run --no-project --python 3.11 --with pillow python sim/assets/build_lod.py

Reads console/public/models/aftershock.glb (from build_glb.py) and writes aftershock_lite.glb next to it:
the same nodes, names, poses, extras and meshes, but no textures. Each textured material keeps a flat
colour, its base colour times the mean of its diffuse texture, so the tower looks the same from the
console's distance. Texture coordinates go too: nothing samples them.

Why: in software WebGL (no GPU, e.g. CI's SwiftShader) the console draws the tower with Lambert shading,
which ignores the normal and roughness maps, yet GLTFLoader still decodes and uploads all three 1k
textures (about 2 MB of the 2.9 MB file). The console loads this file instead when it detects software GL.

Run it again whenever build_glb.py rewrites aftershock.glb; sim/tests/test_assets.py fails while the two
files disagree on nodes or geometry.
"""

import io
import json
import pathlib
import struct

from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
MODELS = HERE.parents[1] / "console" / "public" / "models"
FULL = MODELS / "aftershock.glb"
LITE = MODELS / "aftershock_lite.glb"
DROP_ATTRIBUTES = ("TEXCOORD_0", "TEXCOORD_1", "TANGENT")


def read_glb(path):
    """(json, binary chunk) of a GLB."""
    b = pathlib.Path(path).read_bytes()
    magic, _version, _length = struct.unpack("<4sII", b[:12])
    assert magic == b"glTF", path
    n, kind = struct.unpack("<I4s", b[12:20])
    assert kind == b"JSON"
    j = json.loads(b[20:20 + n])
    rest = b[20 + n:]
    blob = b""
    if rest:
        m, kind = struct.unpack("<I4s", rest[:8])
        assert kind == b"BIN\0"
        blob = rest[8:8 + m]
    return j, blob


def write_glb(path, j, blob):
    text = json.dumps(j, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    blob += b"\0" * (-len(blob) % 4)
    body = struct.pack("<I4s", len(text), b"JSON") + text + struct.pack("<I4s", len(blob), b"BIN\0") + blob
    pathlib.Path(path).write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body)


def _srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def mean_linear_rgb(j, blob, texture_index):
    """Mean colour of a texture in linear RGB (glTF base colour textures are sRGB, factors are linear)."""
    view = j["bufferViews"][j["images"][j["textures"][texture_index]["source"]]["bufferView"]]
    start = view.get("byteOffset", 0)
    img = Image.open(io.BytesIO(blob[start:start + view["byteLength"]])).convert("RGB")
    img = img.resize((64, 64), Image.Resampling.BOX)
    raw = img.tobytes()
    n = len(raw) // 3
    return [sum(_srgb_to_linear(raw[k] / 255) for k in range(i, len(raw), 3)) / n for i in range(3)]


def lite(j, blob):
    """The textureless copy of a glTF (json, blob): same nodes and meshes, flat materials."""
    j = json.loads(json.dumps(j))
    for mat in j.get("materials", []):
        pbr = mat.setdefault("pbrMetallicRoughness", {})
        tex = pbr.pop("baseColorTexture", None)
        if tex is not None:
            factor = pbr.get("baseColorFactor", [1, 1, 1, 1])
            mean = mean_linear_rgb(j, blob, tex["index"])
            pbr["baseColorFactor"] = [round(factor[i] * mean[i], 4) for i in range(3)] + [factor[3]]
        if pbr.pop("metallicRoughnessTexture", None) is not None:
            pbr.setdefault("roughnessFactor", 0.9)
        for key in ("normalTexture", "occlusionTexture", "emissiveTexture"):
            mat.pop(key, None)
    for key in ("textures", "images", "samplers"):
        j.pop(key, None)
    for mesh in j["meshes"]:
        for prim in mesh["primitives"]:
            for attr in DROP_ATTRIBUTES:
                prim["attributes"].pop(attr, None)

    # keep only the accessors and buffer views still referenced, packed into a new buffer
    used = sorted({i for mesh in j["meshes"] for prim in mesh["primitives"]
                   for i in [*prim["attributes"].values(), prim.get("indices")] if i is not None})
    acc_map = {old: new for new, old in enumerate(used)}
    accessors = [j["accessors"][i] for i in used]
    views, view_map, out = [], {}, bytearray()
    for acc in accessors:
        old = acc["bufferView"]
        if old not in view_map:
            v = dict(j["bufferViews"][old])
            start = v.pop("byteOffset", 0)
            out += b"\0" * (-len(out) % 4)
            v["byteOffset"] = len(out)
            v["buffer"] = 0
            out += blob[start:start + v["byteLength"]]
            view_map[old] = len(views)
            views.append(v)
        acc["bufferView"] = view_map[old]
    for mesh in j["meshes"]:
        for prim in mesh["primitives"]:
            prim["attributes"] = {k: acc_map[v] for k, v in prim["attributes"].items()}
            if "indices" in prim:
                prim["indices"] = acc_map[prim["indices"]]
    j["accessors"], j["bufferViews"] = accessors, views
    j["buffers"] = [{"byteLength": len(out)}]
    j.setdefault("asset", {})["generator"] = "sim/assets/build_lod.py (from " + j["asset"].get("generator", "?") + ")"
    return j, bytes(out)


def main():
    j, blob = lite(*read_glb(FULL))
    write_glb(LITE, j, blob)
    print(f"{LITE.relative_to(MODELS.parents[2])}: {LITE.stat().st_size / 1e6:.2f} MB "
          f"(from {FULL.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
