"""POSE-HAS-YAW: every pose the sim publishes carries a usable yaw.

- sensors/scout (coord/CONTRACT.md: {"pose": {"pos": [x, y, z], "yaw": ...}}): on one real B2 rescue
  (tools/run_b2.py, seed 0) every sensors message the perception map gets is booked (GridLevels is
  wrapped by monkeypatch, nothing in the lanes changes). Each pose has a finite yaw in [-pi, pi] (to the 3 dp it is rounded to), and
  while the Scout drives straight (moved over MIN_MOVE between two scans) the yaw points the way it went.
- responder/pose (E2): Responder.pose_message on the backup scene has a finite yaw that follows a turn.
Synthetic poses pin the checks. Skips the real runs without MuJoCo.
"""

import itertools
import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

MIN_MOVE = 0.03                 # metres between two scans before the heading is compared
HEADING_TOL = math.radians(35)  # yaw vs the direction travelled (the Scout turns on the spot and in arcs)


def yaw_problems(poses):
    """[str] for each pose without a finite yaw in [-pi, pi]; poses are {"pos": [x, y, z], "yaw": ...}."""
    out = []
    for i, p in enumerate(poses):
        y = p.get("yaw")
        if not isinstance(y, (int, float)) or not math.isfinite(y) or abs(y) > math.pi + 5e-4:
            out.append(f"pose {i}: yaw {y!r}")
    return out


def angle_diff(a, b):
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


def heading_agreement(poses):
    """(agreeing, compared): straight moves over MIN_MOVE whose yaw (at either end) matches the travel."""
    agree = total = 0
    for a, b in itertools.pairwise(poses):
        dx, dy = b["pos"][0] - a["pos"][0], b["pos"][1] - a["pos"][1]
        if math.hypot(dx, dy) < MIN_MOVE:
            continue
        travel = math.atan2(dy, dx)
        total += 1
        agree += min(angle_diff(a["yaw"], travel), angle_diff(b["yaw"], travel)) <= HEADING_TOL
    return agree, total


def test_missing_nan_and_out_of_range_yaw_are_flagged():
    poses = [{"pos": [0, 0, 0], "yaw": 0.0}, {"pos": [0, 0, 0]}, {"pos": [0, 0, 0], "yaw": float("nan")},
             {"pos": [0, 0, 0], "yaw": 4.0}, {"pos": [0, 0, 0], "yaw": "1"}]
    assert yaw_problems(poses) == ["pose 1: yaw None", "pose 2: yaw nan", "pose 3: yaw 4.0", "pose 4: yaw '1'"]


def test_heading_agreement_compares_only_real_moves():
    poses = [{"pos": [0, 0, 0], "yaw": 0.0}, {"pos": [0.1, 0, 0], "yaw": 0.0},
             {"pos": [0.1, 0.005, 0], "yaw": 3.0},                    # too small to compare
             {"pos": [0.1, 0.2, 0], "yaw": -math.pi / 2}]              # yaw points the wrong way
    assert heading_agreement(poses) == (1, 2)


def test_angle_diff_wraps():
    assert angle_diff(math.pi - 0.01, -math.pi + 0.01) == pytest.approx(0.02)


def test_real_scout_sensor_poses_have_yaw(tmp_path, monkeypatch):
    pytest.importorskip("mujoco")
    import run_b2

    import perception.levels as pl

    poses = []

    class Watched(pl.GridLevels):
        def add_sensors(self, msg):
            poses.append(dict(msg["pose"]))
            return super().add_sensors(msg)

    monkeypatch.setattr(pl, "GridLevels", Watched)
    verdict, _ = run_b2.run(seed=0, out_dir=tmp_path, floor="B2")
    assert len(poses) > 100
    assert yaw_problems(poses) == []
    agree, total = heading_agreement(poses)
    assert total > 20, "too few moves to compare the heading"
    assert agree >= 0.9 * total, f"yaw matched the travel on only {agree}/{total} moves"
    assert verdict["failed"] == [], verdict["failed"]


def test_real_responder_pose_message_has_yaw():
    pytest.importorskip("mujoco")
    import mujoco

    from sim import scene
    from sim.responder import Responder

    m, d = scene.load(scene.BACKUP)
    mujoco.mj_forward(m, d)
    r = Responder(m, d)
    start = r.pose_message(0.0)
    r._set_pose(r.pos[:2], 1.0)
    turned = r.pose_message(0.1)
    assert yaw_problems([start, turned]) == []
    assert turned["yaw"] == pytest.approx(1.0, abs=1e-3)
