"""BASEMENT-ORDER: a real chained rescue log visits every basement in order.

Exercise the actual CLI/log seam with one LevelWorld and the real perception /
planner decision loop. No fake records, mocked run, waypoints or pose edits.
"""

import json
import math
from itertools import pairwise

from tools import run_levels

ORDER = ["L1", "ground", "B1", "B2", "B3"]
FLOOR_Z = {"L1": 0.6, "ground": 0.0, "B1": -0.6, "B2": -1.2, "B3": -1.8}
# 0.3 m/s * 0.1 s = 0.030 m horizontally; slope 0.3 gives 0.03133 m
# in 3D. 0.035 m allows <3.7 mm for seams/roundoff, not a 0.6 m floor snap.
MAX_TICK_JUMP = 0.035


def test_real_saved_log_visits_basements_in_order_without_teleport(tmp_path):
    path = tmp_path / "basements.jsonl"
    assert run_levels.main([
        "--seed", "0", "--max-t", "500", "--out", str(path)
    ]) == 0
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records and records[0]["kind"] == "meta"
    assert all(math.isfinite(r["t"]) for r in records)
    assert all(a["t"] <= b["t"] for a, b in pairwise(records))

    visits = [r for r in records if r["kind"] == "level"]
    assert [r["level"] for r in visits] == ORDER
    assert visits[0]["t"] == 0.0
    assert all(a["t"] < b["t"] for a, b in pairwise(visits))
    legs = [r for r in records if r["kind"] == "leg"]
    assert [r["floor"] for r in legs] == ["B1", "B2", "B3"]
    assert all(r["reached"] is True for r in legs), legs
    assert all(a["t"] < b["t"] for a, b in pairwise(legs))
    for visit, leg in zip(visits[2:], legs):
        assert visit["t"] <= leg["t"], (visit, leg)

    poses = [r for r in records if r["kind"] == "pose"]
    assert len(poses) > 20
    measured_order = []
    for pose in poses:
        assert all(math.isfinite(v) for v in pose["pos"]), pose
        floor = pose["level"]
        if floor == "ramp":
            continue
        # Floor events must agree with the recorded physical sensor height,
        # not merely contain the expected text labels in the expected order.
        # LevelWorld.level() includes ramp mouths within 0.02 m of a floor;
        # allow that classification window plus the log's 1 mm rounding.
        assert abs(pose["pos"][2] - (FLOOR_Z[floor] + 0.075)) < 0.021, pose
        if not measured_order or floor != measured_order[-1]:
            measured_order.append(floor)
    assert measured_order == ORDER
    for before, after in pairwise(poses):
        dt = after["t"] - before["t"]
        assert 0 < dt <= 1.1 + 1e-9, (before, after)
        # Pose records are ~1 Hz, unlike the runner's per-tick maximum below.
        # 0.35 m/s is the tick cap / 0.1 s; 2 mm covers two rounded xyz poses.
        assert math.dist(before["pos"], after["pos"]) <= 0.35 * dt + 0.002, (before, after)

    summaries = [r for r in records if r["kind"] == "summary"]
    assert len(summaries) == 1
    summary = summaries[0]
    assert 0 < summary["max_jump"] <= MAX_TICK_JUMP, summary
    assert abs(summary["final_pos"][2] - (-1.725)) < 0.003, summary
    assert run_levels.evaluate(records)["failed"] == []
