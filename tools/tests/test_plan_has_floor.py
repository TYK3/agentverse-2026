"""PLAN-HAS-FLOOR: real plans retain floor height consistent with Scout poses.

The existing schema has no named plan.floor: floor/ramp identity is encoded by
3D route-cell k at 0.05 m resolution and target z in metres. Check every plan
against recent pose heights and level events on real B2/B3 runs. Routes may
span ramps/floors; requiring every cell to share the current floor is wrong.
This does not add named floor metadata or prove physics/Responder approval.
"""

import json
import math
from itertools import pairwise

import pytest

from tools import run_b2

FLOOR_Z = {"L1": 0.6, "ground": 0.0, "B1": -0.6, "B2": -1.2, "B3": -1.8}


def assert_plans_retain_floor_height(records, target_floor):
    pose = level = None
    starts = set()
    count = 0
    for record in records:
        if record["kind"] == "level":
            level = record["level"]
        elif record["kind"] == "pose":
            pose = record
            if pose["level"] != "ramp":
                assert pose["level"] == level, (pose, level)
                assert abs(pose["pos"][2] - 0.075 - FLOOR_Z[level]) < 0.021, pose
        elif record["kind"] == "plan":
            count += 1
            cells = record["cells"]
            assert cells and pose is not None, record
            assert all(len(c) == 3 and all(type(v) is int for v in c) for c in cells), record
            assert all(-36 <= c[2] <= 12 for c in cells), record
            assert all(abs(a[2] - b[2]) <= 1 for a, b in pairwise(cells)), record
            dt = record["t"] - pose["t"]
            assert 0 <= dt <= 1.1 + 1e-9, (record, pose)
            start_z = cells[0][2] * 0.05
            # Planner start may snap <=3 cells (0.15 m); floor quantization
            # adds <=0.025 m. Between ~1 Hz poses, 0.3 m/s on slope 0.3
            # changes z <=0.09 m/s; 1 mm covers recorded pose rounding.
            tolerance = 0.15 + 0.025 + 0.09 * dt + 0.001
            assert abs(start_z - (pose["pos"][2] - 0.075)) <= tolerance, (record, pose)
            target = record["target"]
            assert len(target) == 3 and all(math.isfinite(v) for v in target), record
            if record["why"] == "probe":
                assert abs(target[2] - start_z) <= 0.176, record
            else:
                # A routed target comes from one of the route's cell heights,
                # with at most 5 mm loss from the log's 2-decimal rounding.
                assert any(abs(target[2] - c[2] * 0.05) <= 0.005 + 1e-9 for c in cells), record
            starts.add(cells[0][2])
    assert count > 20
    expected = [12, 0, -12, -24] + ([-36] if target_floor == "B3" else [])
    assert set(expected) <= starts, (target_floor, starts)


@pytest.mark.parametrize("floor", ["B2", "B3"])
def test_every_real_plan_identifies_floor_through_3d_coordinates(tmp_path, floor):
    verdict, path = run_b2.run(seed=0, max_t=500.0, out_dir=tmp_path, floor=floor)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert verdict["failed"] == [], verdict
    assert_plans_retain_floor_height(records, floor)
