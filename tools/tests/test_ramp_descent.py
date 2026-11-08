"""RAMP-DESCENT: the Scout goes down one storey at a time by driving the ramps.

Between each pair of neighbouring floors a real run must show pose records
labelled "ramp" (LevelWorld.level returns that when the floor under the Scout
is more than 2 cm from any named storey) whose height sits between those two
floors. A direct floor-to-floor hop in the pose labels, a storey skip in the
level events, or ramp poses that never leave a floor height, do not count.

Does not repeat LEVEL-TRANSITION (ramp speed / dwell) or DESCEND-NO-SKIP
(storey sequence only). This file is about riding the ramp itself.
"""

import json
import os

import pytest

# Floor heights from sim.levels.LEVEL_Z; pose z is floor + RIDE.
FLOOR_Z = {"L1": 0.6, "ground": 0.0, "B1": -0.6, "B2": -1.2, "B3": -1.8}
ORDER = ["L1", "ground", "B1", "B2", "B3"]
RIDE = 0.075
BETWEEN = 0.10          # metres off both floor ride-heights: truly on the slope

real = pytest.mark.skipif(os.environ.get("RUN_B2_REAL") != "1",
                          reason="real B2 run, ~20 s: set RUN_B2_REAL=1")


def _ride(name):
    return FLOOR_Z[name] + RIDE


def _compact(labels):
    out = []
    for name in labels:
        if not out or out[-1] != name:
            out.append(name)
    return out


def assert_ramp_descent(records):
    """Each downward storey change is ridden on ramp-labelled poses at mid height."""
    levels = [r for r in records if r.get("kind") == "level"]
    poses = [r for r in records if r.get("kind") == "pose"]
    names = [r["level"] for r in levels]
    assert names, "log has no level records"
    assert names[0] == "L1"
    assert all(n in ORDER for n in names), names
    for a, b in zip(names, names[1:]):
        assert ORDER.index(b) == ORDER.index(a) + 1, f"level events skip or go back: {a} -> {b}"

    for prev, nxt in zip(levels, levels[1:]):
        window = [p for p in poses if prev["t"] <= p.get("t", -1) <= nxt["t"]]
        ramps = [p for p in window if p.get("level") == "ramp" and p.get("pos")]
        assert ramps, f"no ramp pose between {prev['level']} and {nxt['level']}"
        lo, hi = sorted((_ride(prev["level"]), _ride(nxt["level"])))
        mid = [p for p in ramps if lo + BETWEEN < p["pos"][2] < hi - BETWEEN]
        assert mid, (
            f"ramp poses between {prev['level']} and {nxt['level']} never left a floor height")

    labels = []
    for pose in poses:
        name = pose.get("level")
        assert name in ORDER or name == "ramp", f"unknown pose level {name!r} at t={pose.get('t')}"
        if name == "ramp" and pose.get("pos"):
            z = pose["pos"][2]
            on_a_ramp = any(
                min(_ride(a), _ride(b)) - BETWEEN <= z <= max(_ride(a), _ride(b)) + BETWEEN
                for a, b in zip(ORDER, ORDER[1:]))
            assert on_a_ramp, f"ramp pose at t={pose['t']} z={z} is not between adjacent floors"
        labels.append(name)

    seq = _compact(labels)
    for a, b in zip(seq, seq[1:]):
        if a in ORDER and b in ORDER:
            raise AssertionError(f"jumped {a} to {b} with no ramp poses")


def _level(t, name):
    return {"t": t, "kind": "level", "level": name}


def _pose(t, name, z, x=1.0, y=2.0):
    return {"t": t, "kind": "pose", "level": name, "pos": [x, y, z], "state": "moving"}


def _l1_to_ground():
    return [
        _level(0.0, "L1"),
        _pose(0.0, "L1", _ride("L1")),
        _pose(9.0, "ramp", 0.45),
        _pose(15.0, "ramp", 0.30),
        _level(21.6, "ground"),
        _pose(22.0, "ground", _ride("ground")),
    ]


def test_riding_the_ramp_between_neighbouring_floors_passes():
    assert_ramp_descent(_l1_to_ground())


def test_two_storeys_each_need_their_own_ramp():
    rows = _l1_to_ground() + [
        _pose(58.0, "ramp", -0.22),
        _pose(70.0, "ramp", -0.35),
        _level(80.1, "B1"),
        _pose(81.0, "B1", _ride("B1")),
    ]
    assert_ramp_descent(rows)


def test_no_ramp_poses_between_floors_fails():
    rows = [
        _level(0.0, "L1"),
        _pose(0.0, "L1", _ride("L1")),
        _level(22.0, "ground"),
        _pose(22.0, "ground", _ride("ground")),
    ]
    with pytest.raises(AssertionError, match="no ramp pose"):
        assert_ramp_descent(rows)


def test_storey_skip_in_level_events_fails():
    rows = [
        _level(0.0, "L1"),
        _pose(0.0, "L1", _ride("L1")),
        _pose(10.0, "ramp", 0.10),
        _level(30.0, "B1"),
        _pose(30.0, "B1", _ride("B1")),
    ]
    with pytest.raises(AssertionError, match="skip or go back"):
        assert_ramp_descent(rows)


def test_ramp_poses_that_stay_at_floor_height_fail():
    rows = [
        _level(0.0, "L1"),
        _pose(0.0, "L1", _ride("L1")),
        _pose(9.0, "ramp", _ride("L1") - 0.03),
        _level(21.6, "ground"),
        _pose(22.0, "ground", _ride("ground")),
    ]
    with pytest.raises(AssertionError, match="never left a floor height"):
        assert_ramp_descent(rows)


def test_pose_labels_cannot_jump_a_storey_without_a_ramp():
    rows = _l1_to_ground() + [
        _pose(23.0, "B1", _ride("B1")),
    ]
    with pytest.raises(AssertionError, match="jumped ground to B1"):
        assert_ramp_descent(rows)


@real
def test_real_b2_descent_rides_the_ramps(tmp_path):
    pytest.importorskip("mujoco")
    from tools.run_b2 import run

    _verdict, path = run(seed=0, out_dir=tmp_path, floor="B2")
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert_ramp_descent(records)
    names = [r["level"] for r in records if r["kind"] == "level"]
    assert names[:4] == ["L1", "ground", "B1", "B2"]
