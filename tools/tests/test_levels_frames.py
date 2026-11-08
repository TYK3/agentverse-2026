"""LEVELS-LIVE-2 (tools/levels_frames.py): when a frame is taken, how depth is stored, and a real render."""

import json

import numpy as np
import pytest
from PIL import Image

from tools import levels_frames as lf

GOALS = {"B1": (0.75, 1.55, -0.6), "B2": (0.75, 0.8, -1.2), "B3": (0.75, 1.6, -1.8)}


def test_a_frame_only_at_a_stop_beside_the_goal_once_per_floor():
    assert lf.at_stop("arrived", "B1", (0.8, 1.5, -0.5), GOALS, set()) == "B1"
    assert lf.at_stop("blocked", "B2", (0.75, 0.85, -1.1), GOALS, set()) == "B2"
    assert lf.at_stop("moving", "B1", (0.75, 1.55, -0.5), GOALS, set()) is None      # driving past
    assert lf.at_stop("arrived", "B1", (1.5, 1.55, -0.5), GOALS, set()) is None      # stopped, not at the goal
    assert lf.at_stop("arrived", "B1", (0.75, 1.55, -0.5), GOALS, {"B1"}) is None    # already taken
    assert lf.at_stop("arrived", "ground", (0.75, 1.55, 0.1), GOALS, set()) is None  # not a basement floor
    assert lf.at_stop("arrived", "ramp", (0.75, 1.55, -0.3), GOALS, set()) is None


def test_depth_is_millimetres_with_zero_for_no_return():
    mm = lf.depth_png([[0.5, 1.2345], [np.inf, -1.0], [np.nan, 70.0]])
    assert mm.dtype == np.uint16
    assert mm.tolist() == [[500, 1234], [0, 0], [0, 65535]]
    assert lf.depth_png([[0.5, 30.0, 29.9]], far=30.0).tolist() == [[500, 0, 29900]]   # at the far clip = sky


def test_saved_rgbd_round_trips(tmp_path):
    rgb = np.zeros((4, 6, 3), np.uint8)
    rgb[..., 0] = 200
    depth = np.full((4, 6), 1.5)
    depth[0, 0] = 0.0
    info = lf.save_rgbd(tmp_path, "B2", rgb, depth)
    assert info == {"rgb": "B2_rgb.png", "depth": "B2_depth.png", "depth_units": "mm",
                    "depth_min_median_max_m": [1.5, 1.5, 1.5]}
    assert np.array_equal(np.asarray(Image.open(tmp_path / "B2_rgb.png")), rgb)
    back = np.asarray(Image.open(tmp_path / "B2_depth.png"))
    assert back[0, 0] == 0 and back[1, 1] == 1500


def test_the_real_world_captures_from_the_scout_camera_or_says_why_not(tmp_path):
    """A real LevelWorld (sim/scenes/levels.xml). With a GL context, an RGB-D pair is written; without one
    (no GL), the stop is still listed with the reason: both are checked, whichever this machine has.
    Needs mujoco (not installed in CI's tools job, as for the real runs in test_run_b2 / test_run_levels)."""
    pytest.importorskip("mujoco")
    world = lf.frame_world(tmp_path, GOALS)()
    entry = world.capture("B1")
    assert entry["floor"] == "B1" and entry["level"] == "L1" and entry["camera"] == world.camera_name
    assert world.frames == [entry]
    if world.frame_renderer is None:
        assert entry["rgbd"] is None and entry["reason"] == lf.NO_GL
        return
    assert (entry["width"], entry["height"]) == (320, 240)
    rgb = np.asarray(Image.open(tmp_path / "B1_rgb.png"))
    depth = np.asarray(Image.open(tmp_path / "B1_depth.png"))
    assert rgb.shape == (240, 320, 3) and rgb.std() > 1            # a real picture, not a blank
    lo, _, hi = entry["rgbd"]["depth_min_median_max_m"]
    assert 0 < lo < hi < 20                                          # metres inside a 5 x 2.4 m scene
    assert depth.dtype == np.uint16 and (depth > 0).mean() > 0.5


def test_outputs_are_the_log_and_frames_json(tmp_path):
    records = [{"t": 0.0, "kind": "meta", "seed": 3}, {"t": 1.0, "kind": "leg", "floor": "B1", "reached": True}]
    frames = [{"t": 1.0, "floor": "B1", "rgbd": None, "reason": lf.NO_GL}]
    lf.write_outputs(tmp_path / "out", 3, records, frames)
    saved = json.loads((tmp_path / "out" / "frames.json").read_text())
    assert saved == {"seed": 3, "source": "tools/levels_frames.py", "frames": frames}
    lines = (tmp_path / "out" / "levels-3.jsonl").read_text().splitlines()
    assert [json.loads(line) for line in lines] == records
