"""TICK-HAS-POSE: every 1 s window of a real run log has a pose.

The runners log the Scout's pose once a second of sim time (tools/run_levels.py and tools/run_b2.py:
"pose (1 Hz)"), so a replay or a check can follow the Scout the whole way. Two real runs, seed 0: the
chained rescue L1 > B1 > B2 > B3 (run_levels) and the B2 rescue with its slab shift (run_b2). For every
window [n, n + 1) s from 0 up to the log's last record, at least one pose record must fall in it, and
each pose must say where the Scout was (a finite [x, y, z] and its level). Nothing in the runs is changed.
"""

import copy
import itertools
import json
import math

import pytest

pytest.importorskip("mujoco")    # a real sim run; CI's tools lane has no MuJoCo (the full job does)

from tools import run_b2, run_levels

LEVELS = {"L1", "ground", "B1", "B2", "B3", "ramp"}
RUNS = ("run_levels", "run_b2")


@pytest.fixture(scope="module", params=RUNS)
def run_log(request, tmp_path_factory):
    if request.param == "run_levels":
        records = run_levels.run(0)
    else:
        _, path = run_b2.run(0, out_dir=tmp_path_factory.mktemp("tick-has-pose"))
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return request.param, records


def poses(records):
    return [r for r in records if r["kind"] == "pose"]


def empty_windows(records):
    """The whole seconds n (0 <= n <= the log's last t) whose window [n, n + 1) has no pose."""
    end = max(r["t"] for r in records)
    covered = {math.floor(r["t"] + 1e-9) for r in poses(records)}
    return [n for n in range(math.floor(end) + 1) if n not in covered]


def assert_every_window_has_a_pose(records):
    assert poses(records), "a real run log has poses"
    gaps = empty_windows(records)
    assert not gaps, f"no pose in the 1 s window(s) starting at {gaps[:5]} s"
    for p in poses(records):
        pos = p.get("pos")
        assert isinstance(pos, list) and len(pos) == 3 and all(
            isinstance(v, (int, float)) and math.isfinite(v) for v in pos), p
        assert p.get("level") in LEVELS, p


def test_the_real_run_passes(run_log):
    name, records = run_log
    if name == "run_levels":
        failed = [r["name"] for r in records if r["kind"] == "step" and not r["ok"]]
    else:
        failed = next(r for r in records if r["kind"] == "verdict")["failed"]
    assert failed == [], (name, failed)


def test_every_1s_window_has_a_pose(run_log):
    name, records = run_log
    assert_every_window_has_a_pose(records)
    end = max(r["t"] for r in records)
    assert end > 150, (name, end)                         # a whole rescue, minutes of sim time
    ts = [p["t"] for p in poses(records)]
    assert ts == sorted(ts) and len(ts) >= math.floor(end)
    assert max(b - a for a, b in itertools.pairwise(ts)) <= 1.0 + 0.11   # 1 Hz, on a 0.1 s tick


@pytest.mark.parametrize("mutation", ["drop_one", "drop_last", "late_one", "no_pos", "nan_pos", "no_level"])
def test_broken_logs_are_rejected(run_log, mutation):
    _, records = copy.deepcopy(run_log)
    assert_every_window_has_a_pose(records)
    ps = poses(records)
    mid = ps[len(ps) // 2]
    if mutation == "drop_one":
        records.remove(mid)
    elif mutation == "drop_last":
        records.remove(ps[-1])
        records.append({"t": ps[-1]["t"] + 1.5, "kind": "note"})   # the log carries on with no pose
    elif mutation == "late_one":
        mid["t"] += 1.0                                           # the next window then has two, this none
    elif mutation == "no_pos":
        del mid["pos"]
    elif mutation == "nan_pos":
        mid["pos"][0] = float("nan")
    else:
        mid["level"] = "nowhere"
    with pytest.raises(AssertionError):
        assert_every_window_has_a_pose(records)
