"""Load a MuJoCo scene and describe its blocks for the scene/loaded message (T03)."""

import pathlib
import re

import mujoco

SCENES = pathlib.Path(__file__).parent / "scenes"
BACKUP = SCENES / "backup.xml"

# Blocks are free bodies named b<number>; their geom is named b<number>_<label>.
_BLOCK = re.compile(r"^b\d+$")


def load(path=BACKUP):
    """Return (model, data) for the scene at `path`, with derived quantities computed."""
    m = mujoco.MjModel.from_xml_path(str(path))
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    return m, d


def block_ids(m):
    """Body ids of every block (b1, b2, ...) in the model."""
    out = []
    for i in range(m.nbody):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i)
        if name and _BLOCK.match(name):
            out.append(i)
    return out


def _label(m, body_id, name):
    gname = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, m.body_geomadr[body_id]) or ""
    prefix = name + "_"
    return gname[len(prefix):] if gname.startswith(prefix) else "block"


def blocks(m, d):
    """One entry per block: id, label, world position and MuJoCo half-extents (metres)."""
    out = []
    for i in block_ids(m):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i)
        out.append({
            "id": name,
            "label": _label(m, i, name),
            "pos": [round(float(v), 4) for v in d.xpos[i]],
            "size": [round(float(v), 4) for v in m.geom_size[m.body_geomadr[i]]],
        })
    return out


def scene_loaded(m, d, scene="backup"):
    """Payload for the scene/loaded message in coord/CONTRACT.md."""
    return {"scene": scene, "blocks": blocks(m, d)}
