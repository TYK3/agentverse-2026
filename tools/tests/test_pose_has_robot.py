"""POSE-HAS-ROBOT: every pose record in a real run log names its robot (ref POSE-HAS-ROBOT).

A pose says where one robot is. Which robot must be readable from the record itself:
- hub recordings (SIM_RECORD, sim/recorder.py: {"t", "topic", "data"}): `sensors/scout` is the Scout's,
  `responder/pose` the Responder's, and `sim/truth` holds both under `scout` and `responder`;
- descent run logs (tools/run_b2.py, tools/run_levels.py: {"t", "kind", ...}): a `pose` record names its
  robot only if it has a `robot` field.
Each named pose must also carry a 3D position.

Finding: the descent runners' `pose` records name no robot (they are the Scout's, by those scripts'
docstrings, but the record does not say so). That is pinned below as a strict xfail on a real B3 log: it
turns into a failure (XPASS) the day the runner writes `robot`, and the mark must then come off.

Real logs: REAL_HUB, from a real hub run (python tools/demo.py --scene building, every lane, recorded by
SIM_RECORD; 52.8 s of sim time; 528 sensors/scout, 528 responder/pose and
528 sim/truth records; the first and last three of each, payloads trimmed to the pose fields);
REAL_B3_POSES, the first and last three poses of a real run_b2 --floor B3 log (seed 0 on main, 9/9). Full
logs are checked when present: $HUB_LOG (or the newest console/public/runs/demo-*.jsonl) and the newest
runs/b3-*.jsonl; they skip otherwise (CI has none).
"""

import json
import math
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
ROBOTS = {"scout", "responder"}
POSE_TOPICS = {"sensors/scout": "scout", "responder/pose": "responder"}

REAL_HUB = [
    {'t': 0.1, 'topic': 'sensors/scout', 'data': {'t': 0.1, 'pose': {'pos': [2.0, -1.6, 0.26], 'yaw': 1.571}, 'motion': {'state': 'idle', 'target': None}}},
    {'t': 0.1, 'topic': 'responder/pose', 'data': {'t': 0.1, 'pos': [2.0, -2.8, 0.0], 'yaw': 1.571, 'state': 'idle', 'route': None, 'carrying': []}},
    {'t': 0.1, 'topic': 'sim/truth', 'data': {'scene': 'building', 'shaking': False, 'scout': {'pos': [2.0, -1.6, 0.0], 'yaw': 1.571, 'sensor': [2.0, -1.6, 0.26], 'state': 'idle'}, 'casualties': {'c1': [2.0, 2.2, 0.15], 'c2': [10.2, 7.4, 0.15], 'c3': [11.0, 2.8, 0.15], 'c4': [10.8, 5.4, 0.15]}, 'responder': {'pos': [2.0, -2.8, 0.0], 'yaw': 1.571, 'state': 'idle', 'route': None}}},
    {'t': 0.2, 'topic': 'sensors/scout', 'data': {'t': 0.2, 'pose': {'pos': [2.0, -1.6, 0.26], 'yaw': 1.571}, 'motion': {'state': 'idle', 'target': None}}},
    {'t': 0.2, 'topic': 'responder/pose', 'data': {'t': 0.2, 'pos': [2.0, -2.8, 0.0], 'yaw': 1.571, 'state': 'idle', 'route': None, 'carrying': []}},
    {'t': 0.2, 'topic': 'sim/truth', 'data': {'scene': 'building', 'shaking': False, 'scout': {'pos': [2.0, -1.6, 0.0], 'yaw': 1.571, 'sensor': [2.0, -1.6, 0.26], 'state': 'idle'}, 'casualties': {'c1': [2.0, 2.2, 0.15], 'c2': [10.2, 7.4, 0.15], 'c3': [11.0, 2.8, 0.15], 'c4': [10.8, 5.4, 0.15]}, 'responder': {'pos': [2.0, -2.8, 0.0], 'yaw': 1.571, 'state': 'idle', 'route': None}}},
    {'t': 0.3, 'topic': 'sensors/scout', 'data': {'t': 0.3, 'pose': {'pos': [2.0, -1.6, 0.26], 'yaw': 1.571}, 'motion': {'state': 'idle', 'target': None}}},
    {'t': 0.3, 'topic': 'responder/pose', 'data': {'t': 0.3, 'pos': [2.0, -2.8, 0.0], 'yaw': 1.571, 'state': 'idle', 'route': None, 'carrying': []}},
    {'t': 0.3, 'topic': 'sim/truth', 'data': {'scene': 'building', 'shaking': False, 'scout': {'pos': [2.0, -1.6, 0.0], 'yaw': 1.571, 'sensor': [2.0, -1.6, 0.26], 'state': 'idle'}, 'casualties': {'c1': [2.0, 2.2, 0.15], 'c2': [10.2, 7.4, 0.15], 'c3': [11.0, 2.8, 0.15], 'c4': [10.8, 5.4, 0.15]}, 'responder': {'pos': [2.0, -2.8, 0.0], 'yaw': 1.571, 'state': 'idle', 'route': None}}},
    {'t': 52.6, 'topic': 'sensors/scout', 'data': {'t': 52.6, 'pose': {'pos': [2.0, 1.73, 0.26], 'yaw': 1.571}, 'motion': {'state': 'blocked', 'target': [2.0, 2.1]}}},
    {'t': 52.6, 'topic': 'responder/pose', 'data': {'t': 52.6, 'pos': [2.0, -2.8, 0.0], 'yaw': 1.571, 'state': 'idle', 'route': None, 'carrying': []}},
    {'t': 52.6, 'topic': 'sim/truth', 'data': {'scene': 'building', 'shaking': False, 'scout': {'pos': [2.0, 1.73, 0.0], 'yaw': 1.571, 'sensor': [2.0, 1.73, 0.26], 'state': 'blocked'}, 'casualties': {'c1': [2.0, 2.2, 0.15], 'c2': [10.2, 7.4, 0.15], 'c3': [11.0, 2.8, 0.15], 'c4': [10.8, 5.4, 0.15]}, 'responder': {'pos': [2.0, -2.8, 0.0], 'yaw': 1.571, 'state': 'idle', 'route': None}}},
    {'t': 52.7, 'topic': 'sensors/scout', 'data': {'t': 52.7, 'pose': {'pos': [2.0, 1.73, 0.26], 'yaw': 1.571}, 'motion': {'state': 'blocked', 'target': [2.0, 2.1]}}},
    {'t': 52.7, 'topic': 'responder/pose', 'data': {'t': 52.7, 'pos': [2.0, -2.8, 0.0], 'yaw': 1.571, 'state': 'idle', 'route': None, 'carrying': []}},
    {'t': 52.7, 'topic': 'sim/truth', 'data': {'scene': 'building', 'shaking': False, 'scout': {'pos': [2.0, 1.73, 0.0], 'yaw': 1.571, 'sensor': [2.0, 1.73, 0.26], 'state': 'blocked'}, 'casualties': {'c1': [2.0, 2.2, 0.15], 'c2': [10.2, 7.4, 0.15], 'c3': [11.0, 2.8, 0.15], 'c4': [10.8, 5.4, 0.15]}, 'responder': {'pos': [2.0, -2.8, 0.0], 'yaw': 1.571, 'state': 'idle', 'route': None}}},
    {'t': 52.8, 'topic': 'sensors/scout', 'data': {'t': 52.8, 'pose': {'pos': [2.0, 1.73, 0.26], 'yaw': 1.571}, 'motion': {'state': 'blocked', 'target': [2.0, 2.1]}}},
    {'t': 52.8, 'topic': 'responder/pose', 'data': {'t': 52.8, 'pos': [2.0, -2.8, 0.0], 'yaw': 1.571, 'state': 'idle', 'route': None, 'carrying': []}},
    {'t': 52.8, 'topic': 'sim/truth', 'data': {'scene': 'building', 'shaking': False, 'scout': {'pos': [2.0, 1.73, 0.0], 'yaw': 1.571, 'sensor': [2.0, 1.73, 0.26], 'state': 'blocked'}, 'casualties': {'c1': [2.0, 2.2, 0.15], 'c2': [10.2, 7.4, 0.15], 'c3': [11.0, 2.8, 0.15], 'c4': [10.8, 5.4, 0.15]}, 'responder': {'pos': [2.0, -2.8, 0.0], 'yaw': 1.571, 'state': 'idle', 'route': None}}},
]

REAL_B3_POSES = [
    {'t': 0.0, 'kind': 'pose', 'pos': [0.5, 0.5, 0.675], 'state': 'idle', 'level': 'L1', 'cell': [10, 10, 12]},
    {'t': 1.0, 'kind': 'pose', 'pos': [0.507, 0.8, 0.675], 'state': 'moving', 'level': 'L1', 'cell': [10, 15, 12]},
    {'t': 2.0, 'kind': 'pose', 'pos': [0.515, 1.1, 0.675], 'state': 'moving', 'level': 'L1', 'cell': [10, 21, 12]},
    {'t': 228.0, 'kind': 'pose', 'pos': [1.024, 0.803, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [20, 16, -36]},
    {'t': 229.0, 'kind': 'pose', 'pos': [1.024, 1.103, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [20, 22, -36]},
    {'t': 230.0, 'kind': 'pose', 'pos': [0.984, 1.357, -1.725], 'state': 'moving', 'level': 'B3', 'cell': [19, 27, -36]},
]


def _xyz(v):
    return isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) and math.isfinite(x) for x in v)


def poses(records):
    """[(t, robot or None, pos or None)] for every pose a record carries."""
    out = []
    for r in records:
        topic, data = r.get("topic"), r.get("data")
        if topic in POSE_TOPICS and isinstance(data, dict):
            pos = data.get("pose", {}).get("pos") if topic == "sensors/scout" else data.get("pos")
            out.append((r["t"], POSE_TOPICS[topic], pos))
        elif topic == "sim/truth" and isinstance(data, dict):
            for robot in ROBOTS:
                if isinstance(data.get(robot), dict):
                    out.append((r["t"], robot, data[robot].get("pos")))
        elif r.get("kind") == "pose":
            out.append((r["t"], r.get("robot"), r.get("pos")))
    return out


def check(records):
    got = poses(records)
    assert got, "no pose in this log"
    unnamed = [(t, p) for t, robot, p in got if robot not in ROBOTS]
    assert unnamed == [], f"{len(unnamed)} pose(s) name no robot, first at {unnamed[0][0]} s"
    bad = [(t, robot) for t, robot, p in got if not _xyz(p)]
    assert bad == [], f"pose(s) without a 3D position: {bad[:3]}"
    return {robot: sum(1 for _, r, _ in got if r == robot) for robot in ROBOTS}


def test_real_hub_recording_names_every_poses_robot():
    counts = check(REAL_HUB)
    assert counts == {"scout": 12, "responder": 12}                 # 6 sensors/scout + 6 sim/truth; 6 + 6


@pytest.mark.xfail(strict=True, reason="run_b2/run_levels pose records have no robot field (finding)")
def test_real_descent_log_names_every_poses_robot():
    check(REAL_B3_POSES)


def test_full_real_hub_recording():
    env = os.environ.get("HUB_LOG")
    found = [pathlib.Path(env)] if env else sorted((ROOT / "console/public/runs").glob("demo-*.jsonl"),
                                                     key=lambda p: p.stat().st_mtime)
    if not found:
        pytest.skip("no full hub recording: set HUB_LOG or run python tools/demo.py")
    records = [json.loads(line) for line in found[-1].read_text(encoding="utf-8").splitlines() if line.strip()]
    print(found[-1].name, check(records))


def test_the_descent_runner_gap_is_exactly_the_missing_field():
    """Adding `robot` is all a run_b2 pose lacks: with it, the same real poses pass."""
    fixed = [dict(r, robot="scout") for r in REAL_B3_POSES]
    assert check(fixed) == {"scout": 6, "responder": 0}


@pytest.mark.parametrize("record", [
    {"t": 1.0, "kind": "pose", "pos": [0, 0, 0]},                                   # no robot
    {"t": 1.0, "kind": "pose", "robot": "drone", "pos": [0, 0, 0]},                 # not one of ours
    {"t": 1.0, "topic": "responder/pose", "data": {"t": 1.0, "pos": [0, 0]}},       # no 3D position
    {"t": 1.0, "topic": "sensors/scout", "data": {"t": 1.0}},                       # no pose at all
])
def test_unnamed_or_unplaced_poses_fail(record):
    with pytest.raises(AssertionError):
        check([record])
