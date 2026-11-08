"""POSE-LEVEL-Z: every pose in a real chained run agrees with its named floor.

Named levels allow 2 cm at ramp entrances (LevelWorld's level classification)
plus 0.5 mm JSON rounding. Logged z is the Scout sensor origin: floor + 0.075 m.
A ramp is between floor heights and outside the named-floor bands, allowing rounding.
Expected heights are literal contract values, not computed by the sim classifier.
"""

import copy
import json
import math

import pytest

from tools import run_levels

FLOOR_Z = {"L1": 0.6, "ground": 0.0, "B1": -0.6, "B2": -1.2, "B3": -1.8}
SENSOR_RIDE = 0.075
NAMED_TOL = 0.0205
RAMP_MIN_DISTANCE = 0.0195


@pytest.fixture(scope="module")
def recording(tmp_path_factory):
    path = tmp_path_factory.mktemp("pose-level-z") / "levels-0.jsonl"
    assert run_levels.main(["--seed", "0", "--out", str(path)]) == 0
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def assert_pose_level_z(records):
    poses = [r for r in records if r["kind"] == "pose"]
    assert poses, "a real run must contain poses"
    seen = set()
    for pose in poses:
        pos, level = pose["pos"], pose["level"]
        assert len(pos) == 3 and all(type(v) in (int, float) and math.isfinite(v) for v in pos)
        floor = pos[2] - SENSOR_RIDE
        if level in FLOOR_Z:
            assert abs(floor - FLOOR_Z[level]) <= NAMED_TOL, (pose, "z disagrees with named floor")
            seen.add(level)
        else:
            assert level == "ramp", (pose, "unknown level")
            assert min(FLOOR_Z.values()) < floor < max(FLOOR_Z.values())
            assert all(abs(floor - z) >= RAMP_MIN_DISTANCE for z in FLOOR_Z.values()), (
                pose, "a named floor cannot be relabelled as a ramp")
            seen.add("ramp")
    assert seen == {*FLOOR_Z, "ramp"}, "exercise every floor and the connecting ramps"
    levels = [r["level"] for r in records if r["kind"] == "level"]
    assert levels == ["L1", "ground", "B1", "B2", "B3"]
    summary = next(r for r in records if r["kind"] == "summary")
    assert abs(summary["final_pos"][2] - (-1.725)) <= NAMED_TOL


def test_real_chained_run_pose_z_matches_every_claimed_level(recording):
    assert_pose_level_z(recording)


@pytest.mark.parametrize("mutation", ["flatten_basement", "wrong_floor", "omit_sensor_ride",
                                      "floor_as_ramp", "unknown_level", "nonfinite_z"])
def test_mutated_real_pose_log_cannot_pass_level_z(recording, mutation):
    records = copy.deepcopy(recording)
    pose = next(r for r in records if r["kind"] == "pose" and r["level"] == "B2")
    if mutation == "flatten_basement":
        pose["pos"][2] = SENSOR_RIDE
    elif mutation == "wrong_floor":
        pose["level"] = "B1"
    elif mutation == "omit_sensor_ride":
        pose["pos"][2] -= SENSOR_RIDE
    elif mutation == "floor_as_ramp":
        pose["level"] = "ramp"
    elif mutation == "unknown_level":
        pose["level"] = "B4"
    else:
        pose["pos"][2] = float("nan")
    with pytest.raises(AssertionError):
        assert_pose_level_z(records)
