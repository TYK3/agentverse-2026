"""B3-HAS-CASUALTY: a real log reaches c3's B3 goal beside the scene marker.

Definition: the chained runner records a successful B3 leg naming c3, with a
recent B3 pose consistent with its goal and the scene's fixed casualty placement.
This is goal-arrival evidence, not a sensed survivor-find or kit delivery.
"""

import copy
import json
import math

import pytest

from sim import scene
from sim.demo_descent import GOALS
from sim.levels import LEVELS
from tools import run_levels


@pytest.fixture(scope="module")
def recording(tmp_path_factory):
    path = tmp_path_factory.mktemp("b3-casualty") / "levels-0.jsonl"
    assert run_levels.main(["--seed", "0", "--out", str(path)]) == 0
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def assert_b3_has_casualty(records):
    model, data = scene.load(LEVELS)
    marker = model.body("casualty_c3").id
    assert model.geom_bodyid[model.geom("c3_g").id] == marker
    casualty = tuple(float(v) for v in data.xpos[marker])
    assert casualty == pytest.approx((0.45, 2.0, -1.68))
    assert casualty[2] == pytest.approx(-1.8 + 0.12)  # marker origin above the B3 floor
    goal = GOALS["B3"]
    assert goal == pytest.approx((0.75, 1.6, -1.8))
    assert math.dist(goal[:2], casualty[:2]) == pytest.approx(0.5)

    legs = [(i, r) for i, r in enumerate(records) if r["kind"] == "leg" and r["floor"] == "B3"]
    assert len(legs) == 1, "the real run must contain a B3 casualty leg"
    index, leg = legs[0]
    assert leg["casualty"] == "c3" and leg["reached"] is True
    previous = records[:index]
    levels = [r for r in previous if r["kind"] == "level"]
    assert levels and levels[-1]["level"] == "B3"
    poses = [r for r in previous if r["kind"] == "pose" and r["t"] <= leg["t"]]
    assert poses, "a casualty label alone is not pose evidence"
    pose = poses[-1]
    assert pose["level"] == "B3"
    assert len(pose["pos"]) == 3 and all(math.isfinite(v) for v in pose["pos"])
    assert abs(pose["pos"][2] - (-1.725)) <= 0.0205  # floor + sensor ride, with level/rounding tolerance
    age = leg["t"] - pose["t"]
    assert 0 <= age <= 1.1  # the real runner logs poses at 1 Hz
    # Goal arrival allows 0.15 m. The previous sampled pose can additionally
    # be up to 0.3 m/s * sample age away; 2 mm covers rounded coordinates/times.
    assert math.dist(pose["pos"][:2], goal[:2]) <= 0.15 + 0.3 * age + 0.002
    return index, records.index(pose)


def test_real_chained_log_has_c3_goal_arrival_on_b3(recording):
    assert_b3_has_casualty(recording)


@pytest.mark.parametrize("mutation", ["missing_leg", "wrong_casualty", "wrong_floor", "flattened_pose"])
def test_mutated_real_log_cannot_claim_b3_casualty_arrival(recording, mutation):
    records = copy.deepcopy(recording)
    leg_i, pose_i = assert_b3_has_casualty(records)
    if mutation == "missing_leg":
        records.pop(leg_i)
    elif mutation == "wrong_casualty":
        records[leg_i]["casualty"] = "c1"
    elif mutation == "wrong_floor":
        records[leg_i]["floor"] = "B1"
    else:
        records[pose_i]["pos"][2] = 0.075
    with pytest.raises(AssertionError):
        assert_b3_has_casualty(records)
