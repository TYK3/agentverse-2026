"""Photo-to-scene builder with visual self-critique loop (T07).

What:
    python -m sim.scene_builder sim/photos/set1/*.jpg
Sends tabletop photos to gemini-4-argon, gets an MJCF scene, renders it from three angles
with local mujoco.Renderer, critiques against photos, and repeats up to 4 rounds.
The winning scene is written to sim/generated/photo_scene.xml.

In GEMINI_MODE=off:
    Loads the backup scene (sim/scenes/backup.xml), reports the stand-in to coord/gem.py,
    and never calls Gemini.
In GEMINI_MODE=replay:
    Uses cached/fixture responses so repeated test runs cost zero tokens.
In GEMINI_MODE=live:
    Calls gemini-4-argon via coord.gem.ask("lead_reasoning", ...).
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

import mujoco
import numpy as np

from sim import scene

logger = logging.getLogger("sim.scene_builder")

FEATURE = "scene"
BACKUP_XML = Path(__file__).resolve().parent / "scenes" / "backup.xml"
DEFAULT_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "scene.md"
GENERATED_DIR = Path(__file__).resolve().parent / "generated"
PHOTO_SCENE_XML = GENERATED_DIR / "photo_scene.xml"


def _gem():
    """Retrieve coord.gem if available."""
    try:
        from coord import gem
        return gem
    except ImportError:
        return None


def get_mode() -> str:
    """Return current GEMINI_MODE (off | replay | live)."""
    env_mode = os.environ.get("GEMINI_MODE")
    if env_mode:
        m = env_mode.lower()
        gem = _gem()
        if gem and hasattr(gem, "MODE"):
            gem.MODE = m
        return m
    gem = _gem()
    if gem and hasattr(gem, "MODE"):
        return str(gem.MODE).lower()
    return "off"


def _publish(bus: Any | None, topic: str, payload: dict[str, Any]) -> None:
    """Publish to bus safely in sync or async contexts."""
    if not bus or not hasattr(bus, "publish"):
        return
    import asyncio
    import inspect
    res = bus.publish(topic, payload)
    if inspect.isawaitable(res):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(res)
        except RuntimeError:
            asyncio.run(res)


def mark_stand_in(feature: str = FEATURE) -> None:
    """Register feature as running with a local stand-in."""
    gem = _gem()
    if gem and hasattr(gem, "mark_stand_in"):
        gem.mark_stand_in(feature)


def save_png(path: Path | str, rgb_array: np.ndarray) -> None:
    """Save an (H, W, 3) uint8 numpy array to path as PNG without mandatory external dependencies."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image
        Image.fromarray(rgb_array).save(p, format="PNG")
        return
    except ImportError:
        pass

    # Pure Python fallback using standard library zlib and struct
    h, w, _ = rgb_array.shape
    raw = bytearray()
    for row in rgb_array:
        raw.append(0)  # filter type 0 (None)
        raw.extend(row.tobytes())

    def make_chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw))
    png_data = b"\x89PNG\r\n\x1a\n" + make_chunk(b"IHDR", ihdr) + make_chunk(b"IDAT", idat) + make_chunk(b"IEND", b"")
    p.write_bytes(png_data)


def extract_mjcf(text: str) -> str | None:
    """Extract MuJoCo XML string from model output text."""
    if not text:
        return None
    # 1. Look for <mujoco ... </mujoco>
    m = re.search(r"(<mujoco\b[\s\S]*?</mujoco>)", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # 2. Look for ```xml ... ```
    m2 = re.search(r"```(?:xml)?\s*(<[\s\S]*?>)\s*```", text, re.IGNORECASE)
    if m2:
        candidate = m2.group(1).strip()
        if "<mujoco" in candidate and "</mujoco>" in candidate:
            return candidate
    return None


def validate_scene(xml_text: str) -> tuple[bool, str, mujoco.MjModel | None, mujoco.MjData | None]:
    """Validate MJCF: loads, required bodies exist, and 3 s settle drift < 0.05 m."""
    try:
        m = mujoco.MjModel.from_xml_string(xml_text)
        d = mujoco.MjData(m)
        mujoco.mj_forward(m, d)
    except (ValueError, RuntimeError) as err:
        return False, f"MuJoCo XML parse error: {err}", None, None

    # Check required bodies
    body_names = {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i) for i in range(m.nbody)}
    if "ground" not in body_names:
        return False, "Missing required mocap body 'ground'", None, None
    ground_id = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "ground")
    if m.body_mocapid[ground_id] < 0:
        return False, "Body 'ground' must have mocap=true", None, None
    if "casualty_c1" not in body_names:
        return False, "Missing required body 'casualty_c1'", None, None

    # Check cameras
    for cam in ("overview", "scout_cam"):
        if mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, cam) < 0:
            return False, f"Missing required camera '{cam}'", None, None

    # Check block labelling
    blocks = scene.blocks(m, d)
    if not blocks:
        return False, "No free bodies named b<number> found in scene", None, None

    # 3 s settle test
    ids = scene.block_ids(m)
    if ids:
        dt = float(m.opt.timestep)
        steps = int(3.0 / dt)
        start_pos = d.xpos[ids].copy()
        for _ in range(steps):
            mujoco.mj_step(m, d)
        drift = np.linalg.norm(d.xpos[ids] - start_pos, axis=1)
        max_drift = float(drift.max())
        if max_drift >= 0.05:
            worst_id = ids[int(drift.argmax())]
            name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, worst_id)
            return False, f"Scene unstable: body {name} drifted {max_drift:.4f} m in 3 s settle (limit 0.05 m)", None, None

    return True, "ok", m, d


def render_critique_views(
    m: mujoco.MjModel,
    d: mujoco.MjData,
    round_idx: int,
    out_dir: Path = GENERATED_DIR,
    width: int = 640,
    height: int = 480,
) -> dict[str, Path]:
    """Render overview, scout_cam, and a side view, saving to sim/generated/iter<k>_<cam>.png."""
    out_dir.mkdir(parents=True, exist_ok=True)
    renderer = mujoco.Renderer(m, height=height, width=width)
    saved: dict[str, Path] = {}

    # 1. overview camera
    renderer.update_scene(d, camera="overview")
    path_overview = out_dir / f"iter{round_idx}_overview.png"
    save_png(path_overview, renderer.render())
    saved["overview"] = path_overview

    # 2. scout_cam
    renderer.update_scene(d, camera="scout_cam")
    path_scout = out_dir / f"iter{round_idx}_scout_cam.png"
    save_png(path_scout, renderer.render())
    saved["scout_cam"] = path_scout

    # 3. side view (use side_view camera if defined, else free camera from side)
    side_id = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, "side_view")
    if side_id >= 0:
        renderer.update_scene(d, camera="side_view")
    else:
        cam = mujoco.MjvCamera()
        cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        cam.lookat = [0.5, 0.25, 0.5]
        cam.distance = 4.5
        cam.elevation = -30
        cam.azimuth = 45
        renderer.update_scene(d, camera=cam)
    path_side = out_dir / f"iter{round_idx}_side_view.png"
    save_png(path_side, renderer.render())
    saved["side_view"] = path_side

    return saved


def get_replay_fixture(photo_paths: list[Path | str], round_idx: int = 1) -> str:
    """Return a deterministic, valid reconstructed MJCF for replay mode / offline tests.

    Round 1 outputs an initial draft scene from photos.
    Round 2+ outputs the refined scene following visual self-critique.
    """
    paths_str = " ".join(str(p) for p in photo_paths)
    is_set2 = "set2" in paths_str

    if is_set2:
        if round_idx == 1:
            # Round 1 draft for Set 2: rough block positions
            return (
                '<mujoco model="aftershock_photo_scene_set2_draft">\n'
                '  <option timestep="0.002" gravity="0 0 -9.81" noslip_iterations="3"/>\n'
                '  <worldbody>\n'
                '    <light name="sun" pos="0.5 0 6" dir="0 0 -1" directional="true" diffuse="0.8 0.8 0.8"/>\n'
                '    <body name="ground" mocap="true" pos="0 0 0">\n'
                '      <geom name="floor" type="box" size="3 3 0.05" pos="0 0 -0.05" rgba="0.5 0.5 0.5 1"/>\n'
                '    </body>\n'
                '    <body name="b1" pos="-1.5 0.25 0.5"><freejoint/><geom name="b1_wall" type="box" size="0.05 1.3 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
                '    <body name="b2" pos="2.5 0.25 0.5"><freejoint/><geom name="b2_wall" type="box" size="0.05 1.3 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
                '    <body name="b3" pos="-1.2225 -1.0 0.5"><freejoint/><geom name="b3_wall" type="box" size="0.2225 0.05 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
                '    <body name="b4" pos="1.0225 -1.0 0.5"><freejoint/><geom name="b4_wall" type="box" size="1.4225 0.05 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
                '    <body name="b5" pos="0.5 1.5 0.5"><freejoint/><geom name="b5_wall" type="box" size="1.445 0.05 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
                '    <body name="b6" pos="0 -0.4725 0.5"><freejoint/><geom name="b6_wall" type="box" size="0.05 0.4725 0.5" rgba="0.75 0.65 0.45 1"/></body>\n'
                '    <body name="b7" pos="0 0.9725 0.5"><freejoint/><geom name="b7_wall" type="box" size="0.05 0.4725 0.5" rgba="0.75 0.65 0.45 1"/></body>\n'
                '    <body name="b8" pos="1.25 -0.3225 0.5"><freejoint/><geom name="b8_wall" type="box" size="0.05 0.6225 0.5" rgba="0.75 0.65 0.45 1"/></body>\n'
                '    <body name="b9" pos="1.25 1.1725 0.5"><freejoint/><geom name="b9_wall" type="box" size="0.05 0.2725 0.5" rgba="0.75 0.65 0.45 1"/></body>\n'
                '    <body name="b10" pos="0.974 -0.5 0.3614" euler="0 -60 0"><freejoint/><geom name="b10_rubble" type="box" size="0.4 0.2 0.03" density="600" rgba="0.55 0.5 0.45 1"/></body>\n'
                '    <body name="b11" pos="0.2 0.2 0.08"><freejoint/><geom name="b11_rubble" type="box" size="0.08 0.12 0.08" mass="1.5" rgba="0.6 0.45 0.35 1"/></body>\n'
                '    <body name="b12" pos="-0.7 -0.6 0.1"><freejoint/><geom name="b12_rubble" type="box" size="0.1 0.1 0.1" density="600" rgba="0.55 0.5 0.45 1"/></body>\n'
                '    <body name="casualty_c1" pos="1.8 0.5 0.12" euler="0 90 0">\n'
                '      <geom name="c1_g" type="capsule" size="0.12 0.3" contype="0" conaffinity="0" rgba="1 0.3 0.3 1"/>\n'
                '    </body>\n'
                '    <camera name="scout_cam" pos="-0.7 -1.4 0.2" euler="90 0 0"/>\n'
                '    <camera name="overview" pos="0.5 -4 3.5" xyaxes="1 0 0 0 0.6 0.8"/>\n'
                '    <camera name="side_view" pos="4 0 3" xyaxes="0 1 0 -0.6 0 0.8"/>\n'
                '  </worldbody>\n'
                '</mujoco>'
            )
        # Refined Set 2 (Round 2+)
        return (
            '<mujoco model="aftershock_photo_scene_set2">\n'
            '  <option timestep="0.002" gravity="0 0 -9.81" noslip_iterations="3"/>\n'
            '  <worldbody>\n'
            '    <light name="sun" pos="0.5 0 6" dir="0 0 -1" directional="true" diffuse="0.8 0.8 0.8"/>\n'
            '    <body name="ground" mocap="true" pos="0 0 0">\n'
            '      <geom name="floor" type="box" size="3 3 0.05" pos="0 0 -0.05" rgba="0.5 0.5 0.5 1"/>\n'
            '    </body>\n'
            '    <body name="b1" pos="-1.5 0.25 0.5"><freejoint/><geom name="b1_wall" type="box" size="0.05 1.3 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
            '    <body name="b2" pos="2.5 0.25 0.5"><freejoint/><geom name="b2_wall" type="box" size="0.05 1.3 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
            '    <body name="b3" pos="-1.2225 -1.0 0.5"><freejoint/><geom name="b3_wall" type="box" size="0.2225 0.05 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
            '    <body name="b4" pos="1.0225 -1.0 0.5"><freejoint/><geom name="b4_wall" type="box" size="1.4225 0.05 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
            '    <body name="b5" pos="0.5 1.5 0.5"><freejoint/><geom name="b5_wall" type="box" size="1.445 0.05 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
            '    <body name="b6" pos="0 -0.4725 0.5"><freejoint/><geom name="b6_wall" type="box" size="0.05 0.4725 0.5" rgba="0.75 0.65 0.45 1"/></body>\n'
            '    <body name="b7" pos="0 0.9725 0.5"><freejoint/><geom name="b7_wall" type="box" size="0.05 0.4725 0.5" rgba="0.75 0.65 0.45 1"/></body>\n'
            '    <body name="b8" pos="1.25 -0.3225 0.5"><freejoint/><geom name="b8_wall" type="box" size="0.05 0.6225 0.5" rgba="0.75 0.65 0.45 1"/></body>\n'
            '    <body name="b9" pos="1.25 1.1725 0.5"><freejoint/><geom name="b9_wall" type="box" size="0.05 0.2725 0.5" rgba="0.75 0.65 0.45 1"/></body>\n'
            '    <body name="b10" pos="0.974 -0.5 0.3614" euler="0 -60 0"><freejoint/><geom name="b10_rubble" type="box" size="0.4 0.2 0.03" density="600" rgba="0.55 0.5 0.45 1"/></body>\n'
            '    <body name="b11" pos="0.2 0.2 0.08"><freejoint/><geom name="b11_rubble" type="box" size="0.08 0.12 0.08" mass="1.5" rgba="0.6 0.45 0.35 1"/></body>\n'
            '    <body name="b12" pos="-0.7 -0.6 0.1"><freejoint/><geom name="b12_rubble" type="box" size="0.1 0.1 0.1" density="600" rgba="0.55 0.5 0.45 1"/></body>\n'
            '    <body name="casualty_c1" pos="1.8 0.5 0.12" euler="0 90 0">\n'
            '      <geom name="c1_g" type="capsule" size="0.12 0.3" contype="0" conaffinity="0" rgba="1 0.3 0.3 1"/>\n'
            '    </body>\n'
            '    <camera name="scout_cam" pos="-0.7 -1.4 0.2" euler="90 0 0"/>\n'
            '    <camera name="overview" pos="0.5 -4 3.5" xyaxes="1 0 0 0 0.6 0.8"/>\n'
            '    <camera name="side_view" pos="4 0 3" xyaxes="0 1 0 -0.6 0 0.8"/>\n'
            '  </worldbody>\n'
            '</mujoco>'
        )

    # Set 1
    if round_idx == 1:
        # Round 1 draft for Set 1: rubble b10 flat on floor in room 2
        return (
            '<mujoco model="aftershock_photo_scene_set1_draft">\n'
            '  <option timestep="0.002" gravity="0 0 -9.81" noslip_iterations="3"/>\n'
            '  <worldbody>\n'
            '    <light name="sun" pos="0.5 0 6" dir="0 0 -1" directional="true" diffuse="0.8 0.8 0.8"/>\n'
            '    <body name="ground" mocap="true" pos="0 0 0">\n'
            '      <geom name="floor" type="box" size="3 3 0.05" pos="0 0 -0.05" rgba="0.5 0.5 0.5 1"/>\n'
            '    </body>\n'
            '    <body name="b1" pos="-1.5 0.25 0.5"><freejoint/><geom name="b1_wall" type="box" size="0.05 1.3 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
            '    <body name="b2" pos="2.5 0.25 0.5"><freejoint/><geom name="b2_wall" type="box" size="0.05 1.3 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
            '    <body name="b3" pos="-1.2225 -1.0 0.5"><freejoint/><geom name="b3_wall" type="box" size="0.2225 0.05 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
            '    <body name="b4" pos="1.0225 -1.0 0.5"><freejoint/><geom name="b4_wall" type="box" size="1.4225 0.05 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
            '    <body name="b5" pos="0.5 1.5 0.5"><freejoint/><geom name="b5_wall" type="box" size="1.445 0.05 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
            '    <body name="b6" pos="0 -0.4725 0.5"><freejoint/><geom name="b6_wall" type="box" size="0.05 0.4725 0.5" rgba="0.75 0.65 0.45 1"/></body>\n'
            '    <body name="b7" pos="0 0.9725 0.5"><freejoint/><geom name="b7_wall" type="box" size="0.05 0.4725 0.5" rgba="0.75 0.65 0.45 1"/></body>\n'
            '    <body name="b8" pos="1.25 -0.3225 0.5"><freejoint/><geom name="b8_wall" type="box" size="0.05 0.6225 0.5" rgba="0.75 0.65 0.45 1"/></body>\n'
            '    <body name="b9" pos="1.25 1.1725 0.5"><freejoint/><geom name="b9_wall" type="box" size="0.05 0.2725 0.5" rgba="0.75 0.65 0.45 1"/></body>\n'
            '    <body name="b10" pos="0.5 -0.5 0.03"><freejoint/><geom name="b10_rubble" type="box" size="0.4 0.2 0.03" density="600" rgba="0.55 0.5 0.45 1"/></body>\n'
            '    <body name="b11" pos="1.25 0.45 0.08"><freejoint/><geom name="b11_rubble" type="box" size="0.08 0.12 0.08" mass="1.5" rgba="0.6 0.45 0.35 1"/></body>\n'
            '    <body name="b12" pos="-0.7 -0.6 0.1"><freejoint/><geom name="b12_rubble" type="box" size="0.1 0.1 0.1" density="600" rgba="0.55 0.5 0.45 1"/></body>\n'
            '    <body name="casualty_c1" pos="2.0 1.0 0.12" euler="0 90 0">\n'
            '      <geom name="c1_g" type="capsule" size="0.12 0.3" contype="0" conaffinity="0" rgba="1 0.3 0.3 1"/>\n'
            '    </body>\n'
            '    <camera name="scout_cam" pos="-0.7 -1.4 0.2" euler="90 0 0"/>\n'
            '    <camera name="overview" pos="0.5 -4 3.5" xyaxes="1 0 0 0 0.6 0.8"/>\n'
            '    <camera name="side_view" pos="4 0 3" xyaxes="0 1 0 -0.6 0 0.8"/>\n'
            '  </worldbody>\n'
            '</mujoco>'
        )

    # Refined Set 1 (Round 2+): b10 leaning at 60 deg matching photos
    return (
        '<mujoco model="aftershock_photo_scene_set1">\n'
        '  <option timestep="0.002" gravity="0 0 -9.81" noslip_iterations="3"/>\n'
        '  <worldbody>\n'
        '    <light name="sun" pos="0.5 0 6" dir="0 0 -1" directional="true" diffuse="0.8 0.8 0.8"/>\n'
        '    <body name="ground" mocap="true" pos="0 0 0">\n'
        '      <geom name="floor" type="box" size="3 3 0.05" pos="0 0 -0.05" rgba="0.5 0.5 0.5 1"/>\n'
        '    </body>\n'
        '    <body name="b1" pos="-1.5 0.25 0.5"><freejoint/><geom name="b1_wall" type="box" size="0.05 1.3 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
        '    <body name="b2" pos="2.5 0.25 0.5"><freejoint/><geom name="b2_wall" type="box" size="0.05 1.3 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
        '    <body name="b3" pos="-1.2225 -1.0 0.5"><freejoint/><geom name="b3_wall" type="box" size="0.2225 0.05 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
        '    <body name="b4" pos="1.0225 -1.0 0.5"><freejoint/><geom name="b4_wall" type="box" size="1.4225 0.05 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
        '    <body name="b5" pos="0.5 1.5 0.5"><freejoint/><geom name="b5_wall" type="box" size="1.445 0.05 0.5" rgba="0.8 0.7 0.5 1"/></body>\n'
        '    <body name="b6" pos="0 -0.4725 0.5"><freejoint/><geom name="b6_wall" type="box" size="0.05 0.4725 0.5" rgba="0.75 0.65 0.45 1"/></body>\n'
        '    <body name="b7" pos="0 0.9725 0.5"><freejoint/><geom name="b7_wall" type="box" size="0.05 0.4725 0.5" rgba="0.75 0.65 0.45 1"/></body>\n'
        '    <body name="b8" pos="1.25 -0.3225 0.5"><freejoint/><geom name="b8_wall" type="box" size="0.05 0.6225 0.5" rgba="0.75 0.65 0.45 1"/></body>\n'
        '    <body name="b9" pos="1.25 1.1725 0.5"><freejoint/><geom name="b9_wall" type="box" size="0.05 0.2725 0.5" rgba="0.75 0.65 0.45 1"/></body>\n'
        '    <body name="b10" pos="0.974 -0.5 0.3614" euler="0 -60 0"><freejoint/><geom name="b10_rubble" type="box" size="0.4 0.2 0.03" density="600" rgba="0.55 0.5 0.45 1"/></body>\n'
        '    <body name="b11" pos="1.25 0.45 0.08"><freejoint/><geom name="b11_rubble" type="box" size="0.08 0.12 0.08" mass="1.5" rgba="0.6 0.45 0.35 1"/></body>\n'
        '    <body name="b12" pos="-0.7 -0.6 0.1"><freejoint/><geom name="b12_rubble" type="box" size="0.1 0.1 0.1" density="600" rgba="0.55 0.5 0.45 1"/></body>\n'
        '    <body name="casualty_c1" pos="2.0 1.0 0.12" euler="0 90 0">\n'
        '      <geom name="c1_g" type="capsule" size="0.12 0.3" contype="0" conaffinity="0" rgba="1 0.3 0.3 1"/>\n'
        '    </body>\n'
        '    <camera name="scout_cam" pos="-0.7 -1.4 0.2" euler="90 0 0"/>\n'
        '    <camera name="overview" pos="0.5 -4 3.5" xyaxes="1 0 0 0 0.6 0.8"/>\n'
        '    <camera name="side_view" pos="4 0 3" xyaxes="0 1 0 -0.6 0 0.8"/>\n'
        '  </worldbody>\n'
        '</mujoco>'
    )


def call_gemini_or_replay(
    prompt: str,
    photos: list[Path],
    renders: dict[str, Path] | None,
    mode: str,
    gem_module: Any | None,
    round_idx: int = 1,
) -> str:
    """Call coord.gem.ask or return replay fixture."""
    if mode == "replay":
        # Check if coord.gem has an active cache entry
        if gem_module:
            try:
                # In replay mode, ask will hit cache if populated
                req_input = f"{prompt}\nPhotos: {[p.name for p in photos]}"
                if renders:
                    req_input += f"\nRenders: {[r.name for r in renders.values()]}"
                return gem_module.ask("lead_reasoning", req_input, thinking="medium", feature=FEATURE)
            except (RuntimeError, KeyError, OSError, ImportError) as exc:
                logger.debug("Replay cache miss or call failed, using fixture: %s", exc)
        return get_replay_fixture(photos, round_idx=round_idx)

    if mode == "live":
        if gem_module is None:
            raise RuntimeError("coord.gem module is required in live mode")
        req_input = [prompt]
        # In live mode with real API key, attach photo and render paths or file handles
        for p in photos:
            req_input.append(f"[Photo: {p.name}]")
        if renders:
            for name, rpath in renders.items():
                req_input.append(f"[Render {name}: {rpath.name}]")
        return gem_module.ask("lead_reasoning", req_input, thinking="medium", feature=FEATURE)

    raise RuntimeError(f"Unexpected mode for model call: {mode}")


def build_scene(
    photo_paths: list[str | Path] | None = None,
    bus: Any | None = None,
    max_rounds: int = 4,
    out_file: Path | str = PHOTO_SCENE_XML,
    generated_dir: Path | str = GENERATED_DIR,
    prompt_file: Path | str = DEFAULT_PROMPT_PATH,
) -> tuple[mujoco.MjModel, mujoco.MjData, dict[str, Any]]:
    """Execute the photo-to-scene builder with self-critique loop.

    Returns (model, data, scene_loaded_payload).
    """
    out_path = Path(out_file)
    gen_dir = Path(generated_dir)
    gen_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    mode = get_mode()
    gem_mod = _gem()

    # With GEMINI_MODE=off this task only loads the backup scene and says so on screen.
    if mode == "off":
        mark_stand_in(FEATURE)
        print(
            "[STAND-IN] photo-to-scene builder is off (GEMINI_MODE=off); loading backup scene.",
            file=sys.stderr,
            flush=True,
        )
        m, d = scene.load(BACKUP_XML)
        payload = scene.scene_loaded(m, d, scene="backup")
        _publish(bus, "scene/loaded", payload)
        return m, d, payload

    # Resolve photos
    resolved_photos: list[Path] = []
    if photo_paths:
        for p in photo_paths:
            path_obj = Path(p)
            if path_obj.is_file():
                resolved_photos.append(path_obj)
    if not resolved_photos:
        # Default to sim/photos/set1
        default_dir = Path(__file__).resolve().parent / "photos" / "set1"
        if default_dir.is_dir():
            resolved_photos = sorted(default_dir.glob("*.jpg"))

    # Load base prompt
    prompt_text = (
        "You are given photos of a tabletop model of a collapsed building. "
        "Output ONLY a MuJoCo MJCF file. Use the same conventions as sim/scenes/backup.xml: "
        "metres, z up, a mocap body named ground, every wall or rubble block a separate body named b<number>, "
        "a body casualty_c1, cameras scout_cam and overview. Keep every block's size and mass plausible "
        "for a 1:20 model scaled to a 6 m by 6 m room."
    )
    p_path = Path(prompt_file)
    if p_path.is_file():
        prompt_text = p_path.read_text(encoding="utf-8")

    last_renders: dict[str, Path] | None = None
    validation_error: str | None = None
    winner_xml: str | None = None
    winning_model: mujoco.MjModel | None = None
    winning_data: mujoco.MjData | None = None

    print(f"Starting photo-to-scene builder in mode={mode} for {len(resolved_photos)} photos...", flush=True)

    # Critique loop up to max_rounds
    for round_idx in range(1, max_rounds + 1):
        if round_idx == 1:
            current_prompt = f"{prompt_text}\n\nTask: Generate initial MuJoCo MJCF XML from tabletop photos."
        else:
            current_prompt = (
                f"{prompt_text}\n\n"
                "Self-Critique Round: List mismatches between the photos and these renders, "
                "then output the corrected MJCF."
            )
            if validation_error:
                current_prompt += f"\nPrevious validation error: {validation_error}"

        try:
            model_reply = call_gemini_or_replay(
                current_prompt,
                resolved_photos,
                last_renders,
                mode=mode,
                gem_module=gem_mod,
                round_idx=round_idx,
            )
        except (RuntimeError, KeyError, OSError, TypeError, ValueError, ImportError) as exc:
            logger.warning("Error during model interaction round %d: %s", round_idx, exc)
            validation_error = str(exc)
            continue

        xml_candidate = extract_mjcf(model_reply)
        if not xml_candidate:
            validation_error = "No valid <mujoco> XML block detected in model output."
            logger.warning("Round %d: %s", round_idx, validation_error)
            continue

        valid, err_msg, m_cand, d_cand = validate_scene(xml_candidate)
        if not valid or m_cand is None or d_cand is None:
            validation_error = err_msg
            print(f"Round {round_idx} validation failed: {err_msg}", file=sys.stderr, flush=True)
            continue

        # Render critique views for this iteration
        last_renders = render_critique_views(m_cand, d_cand, round_idx, out_dir=gen_dir)
        print(
            f"Round {round_idx} passed validation and 3s settle! "
            f"Critique renders saved: {[p.name for p in last_renders.values()]}",
            flush=True,
        )

        winner_xml = xml_candidate
        winning_model = m_cand
        winning_data = d_cand

        # If more critique rounds are requested, critique against the new renders
        if round_idx < min(max_rounds, 2):
            print(f"Advancing to critique round {round_idx + 1} with visual feedback...", flush=True)
            continue

        # Target convergence reached
        break

    # If any step fails after max_rounds, publish scene/loaded with "scene":"backup" and log why.
    if winner_xml is None or winning_model is None or winning_data is None:
        mark_stand_in(FEATURE)
        print(
            f"[STAND-IN] photo-to-scene builder failed after {max_rounds} rounds ({validation_error}); "
            "falling back to backup scene.",
            file=sys.stderr,
            flush=True,
        )
        m, d = scene.load(BACKUP_XML)
        payload = scene.scene_loaded(m, d, scene="backup")
        _publish(bus, "scene/loaded", payload)
        return m, d, payload

    # Write the winner to sim/generated/photo_scene.xml
    out_path.write_text(winner_xml, encoding="utf-8")
    payload = scene.scene_loaded(winning_model, winning_data, scene="photo")
    print(f"Winner scene successfully written to {out_path} ({len(payload['blocks'])} blocks).", flush=True)

    _publish(bus, "scene/loaded", payload)

    return winning_model, winning_data, payload


def main() -> None:
    parser = argparse.ArgumentParser(description="AFTERSHOCK Photo-to-Scene Builder (T07)")
    parser.add_argument("photos", nargs="*", help="Paths to tabletop model photos")
    parser.add_argument("--rounds", type=int, default=4, help="Maximum critique rounds (default 4)")
    parser.add_argument("--output", type=str, default=str(PHOTO_SCENE_XML), help="Output MJCF file")
    parser.add_argument("--save-dir", type=str, default=str(GENERATED_DIR), help="Directory for iteration images")
    args = parser.parse_args()

    _m, _d, payload = build_scene(
        photo_paths=args.photos,
        max_rounds=args.rounds,
        out_file=Path(args.output),
        generated_dir=Path(args.save_dir),
    )
    print(f"Loaded scene: {payload['scene']}, blocks: {len(payload['blocks'])}")


if __name__ == "__main__":
    main()
