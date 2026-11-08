"""SHIFT-HAS-POSE: every slab shift in a real run_b2 log sits between two pose records that agree with it.

tools/run_b2.py logs a "pose" each sim second and one "shift" record when the slab drops, with the Scout's
position at that moment ("scout"). For every shift record this checks that:

  - a pose comes before it and a pose comes after it in the log, at or before / at or after its time;
  - those two poses are at most one pose interval (1 s) apart: no gap hides where the Scout was;
  - both poses are on the shift's floor (the slab drops on the target floor, with the Scout there);
  - the Scout's position in the shift record is reachable from each pose at driving speed, in the time
    between them, and its height matches theirs: the shift happened where the poses say the Scout was.

The checked-in real B2 seed-0 log (console/tests/fixtures/b2-seed0.jsonl) runs in CI, and copies of it with
broken shifts must fail. RUN_B2_REAL=1 also runs tools/run_b2.py --floor B2 and B3 seed 0 in MuJoCo
(about 2 min) and checks those fresh logs.
"""

import copy
import json
import math
import os
import pathlib

import pytest

from tools import run_b2

ROOT = pathlib.Path(__file__).resolve().parents[2]
REAL_B2 = ROOT / "console" / "tests" / "fixtures" / "b2-seed0.jsonl"
POSE_EVERY = 1.0           # run_b2 logs a pose each sim second
SPEED = run_b2.MAX_JUMP / 0.1   # 0.35 m/s: run_b2's bound on the Scout's motion
ROUND = 0.002              # positions are logged to 1 mm
Z_TOL = 0.02               # the shift is on a floor: the Scout's height matches the bracketing poses


def load(path):
    return [json.loads(line) for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines() if line]


def shift_problems(records):
    """Every way a shift record is not bracketed by agreeing poses, as short strings; [] means none."""
    shifts = [(i, r) for i, r in enumerate(records) if r["kind"] == "shift"]
    if not shifts:
        return ["no shift record"]
    bad = []
    for i, s in shifts:
        before = next((r for r in reversed(records[:i]) if r["kind"] == "pose"), None)
        after = next((r for r in records[i + 1:] if r["kind"] == "pose"), None)
        where = f"shift at t={s['t']}"
        if before is None or after is None:
            bad.append(f"{where}: no pose {'before' if before is None else 'after'} it")
            continue
        if not before["t"] <= s["t"] <= after["t"]:
            bad.append(f"{where}: not between its poses at t={before['t']} and t={after['t']}")
            continue
        gap = round(after["t"] - before["t"], 3)
        if gap > POSE_EVERY + 1e-6:
            bad.append(f"{where}: its poses are {gap} s apart")
        for pose in (before, after):
            if pose["level"] != s["level"]:
                bad.append(f"{where}: pose at t={pose['t']} is on {pose['level']}, the shift on {s['level']}")
        scout = s.get("scout")
        if not (isinstance(scout, list) and len(scout) == 3):
            bad.append(f"{where}: no scout position")
            continue
        for pose in (before, after):
            dt = abs(s["t"] - pose["t"])
            flat = math.dist(scout[:2], pose["pos"][:2])
            if flat > SPEED * dt + ROUND:
                bad.append(f"{where}: Scout {flat:.3f} m from the pose at t={pose['t']} ({dt:.1f} s away)")
            if abs(scout[2] - pose["pos"][2]) > Z_TOL:
                bad.append(f"{where}: Scout at z {scout[2]}, the pose at t={pose['t']} at z {pose['pos'][2]}")
    return bad


@pytest.fixture(scope="module")
def real_b2():
    return load(REAL_B2)


def test_the_real_b2_shift_sits_between_two_agreeing_poses(real_b2):
    assert [r["level"] for r in real_b2 if r["kind"] == "shift"] == ["B2"]
    assert shift_problems(real_b2) == []


def _drop_poses_round_shift(out):
    i = next(i for i, r in enumerate(out) if r["kind"] == "shift")
    t = out[i]["t"]
    out[:] = [r for r in out if not (r["kind"] == "pose" and abs(r["t"] - t) < 2.5)]


def _scout_elsewhere(out):
    next(r for r in out if r["kind"] == "shift")["scout"][0] += 1.0


def _scout_on_another_floor(out):
    next(r for r in out if r["kind"] == "shift")["scout"][2] += 0.6


def _shift_on_wrong_floor(out):
    next(r for r in out if r["kind"] == "shift")["level"] = "B1"


def _shift_after_the_last_pose(out):
    s = next(r for r in out if r["kind"] == "shift")
    out.remove(s)
    last = max(i for i, r in enumerate(out) if r["kind"] == "pose")
    out.insert(last + 1, s)
    s["t"] = out[last]["t"] + 0.5


def _shift_without_scout(out):
    del next(r for r in out if r["kind"] == "shift")["scout"]


BROKEN = {
    "poses around the shift missing": (_drop_poses_round_shift, "apart"),
    "Scout 1 m from where the poses put it": (_scout_elsewhere, "m from the pose"),
    "Scout a floor above its poses": (_scout_on_another_floor, "at z"),
    "shift on a floor the poses are not on": (_shift_on_wrong_floor, "the shift on B1"),
    "shift after the last pose": (_shift_after_the_last_pose, "no pose after"),
    "shift without the Scout's position": (_shift_without_scout, "no scout position"),
}


@pytest.mark.parametrize("name", BROKEN)
def test_a_broken_shift_is_caught(real_b2, name):
    change, expect = BROKEN[name]
    out = copy.deepcopy(real_b2)
    change(out)
    bad = shift_problems(out)
    assert any(expect in line for line in bad), f"{name}: not caught; found {bad}"


def test_a_log_without_a_shift_fails(real_b2):
    assert shift_problems([r for r in real_b2 if r["kind"] != "shift"]) == ["no shift record"]


@pytest.mark.skipif(os.environ.get("RUN_B2_REAL") != "1", reason="real MuJoCo runs: set RUN_B2_REAL=1 (~2 min)")
@pytest.mark.parametrize("floor", ["B2", "B3"])
def test_fresh_real_shift_logs(tmp_path, floor):
    pytest.importorskip("mujoco")
    _, path = run_b2.run(seed=0, out_dir=tmp_path, floor=floor)
    records = load(path)
    assert [r["level"] for r in records if r["kind"] == "shift"] == [floor]
    assert shift_problems(records) == []
