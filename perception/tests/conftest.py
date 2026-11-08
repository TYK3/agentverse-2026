"""Pick a headless MuJoCo GL backend before tests import mujoco.

``sim.sensors.make_renderer`` returns None on Linux when MUJOCO_GL and DISPLAY
are both unset, so GLFW cannot abort the process. Camera-frame checks then
skip. Prefer EGL (as tools/run_local.sh does), then OSMesa, and only keep a
backend that can actually construct a renderer.
"""

import os
import subprocess
import sys

import pytest

_PROBE = """
import mujoco
m = mujoco.MjModel.from_xml_string('<mujoco><worldbody><geom size="0.1"/></worldbody></mujoco>')
mujoco.Renderer(m, 8, 8)
"""


def _backend_works(name):
    env = os.environ.copy()
    env["MUJOCO_GL"] = name
    try:
        run = subprocess.run(
            [sys.executable, "-c", _PROBE],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return run.returncode == 0


def _select_mujoco_gl():
    if os.environ.get("MUJOCO_GL"):
        return
    for name in ("egl", "osmesa"):
        if _backend_works(name):
            os.environ["MUJOCO_GL"] = name
            return


_select_mujoco_gl()


@pytest.fixture
def require_camera_renderer():
    """Return the world if it can render frames; skip only when no backend works."""

    def _check(world):
        if getattr(world, "renderer", None) is not None:
            return world
        backend = os.environ.get("MUJOCO_GL") or "unset"
        pytest.skip(f"no GL context for camera frames (MUJOCO_GL={backend})")

    return _check
