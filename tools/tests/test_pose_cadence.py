"""POSE-CADENCE: a real run_b2 log has exactly one Scout pose per sim second, on the second, for the whole run.

tools/run_b2.py writes a "pose" record each sim second (t 0, 1, 2, ...) and ends with "summary" and "verdict".
Replays, the console timeline and the no-teleport checks all read those poses, so this checks that:

  - the pose times are exactly 0, 1, 2, ..., N-1: whole seconds, none missing, none repeated;
  - the poses cover the whole run: N - 1 == floor(summary.t), so the last second before the end has its pose;
  - the log is in time order (no record goes back in time) and every pose sits at its place in it;
  - summary and verdict come after the last pose and are the last two records.

tools/tests/test_no_teleport.py (NO-TELEPORT) only asks that poses are never more than 1 s apart, which a log
with poses at 0.5 s, doubled seconds or a missing tail still passes. The checked-in real B2 seed-0 log runs in
CI and broken copies of it must fail; RUN_B2_REAL=1 also checks fresh --floor B1/B2/B3 seed 0 runs (~3 min).
"""

import copy
import itertools
import json
import math
import os
import pathlib

import pytest

from tools import run_b2

ROOT = pathlib.Path(__file__).resolve().parents[2]
REAL_B2 = ROOT / "console" / "tests" / "fixtures" / "b2-seed0.jsonl"
EPS = 1e-6


def load(path):
    return [json.loads(line) for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines() if line]


def cadence_problems(records):
    """Every way the pose cadence breaks, as short strings; [] means none."""
    bad = []
    times = [r["t"] for r in records if r["kind"] == "pose"]
    if not times:
        return ["no pose records"]
    off_second = [t for t in times if abs(t - round(t)) > EPS]
    if off_second:
        bad.append(f"poses off the whole second at t={off_second[:3]}")
    seconds = [round(t) for t in times]
    if seconds != list(range(len(seconds))):
        repeated = sorted({s for s in seconds if seconds.count(s) > 1})
        missing = sorted(set(range(max(seconds) + 1)) - set(seconds))
        if repeated:
            bad.append(f"repeated pose seconds {repeated[:5]}")
        if missing:
            bad.append(f"missing pose seconds {missing[:5]}")
        if not repeated and not missing:
            bad.append("pose seconds out of order")
    summary = next((r for r in records if r["kind"] == "summary"), None)
    if summary is None:
        bad.append("no summary record")
    elif math.floor(summary["t"] + EPS) != seconds[-1]:
        bad.append(f"last pose at t={times[-1]}, but the run ended at t={summary['t']}")
    back = [(a["t"], b["t"], b["kind"]) for a, b in itertools.pairwise(records) if b["t"] < a["t"] - EPS]
    if back:
        bad.append(f"time goes back: {back[:3]}")
    if [r["kind"] for r in records[-2:]] != ["summary", "verdict"]:
        bad.append(f"the log ends with {[r['kind'] for r in records[-2:]]}, not summary then verdict")
    last_pose = max(i for i, r in enumerate(records) if r["kind"] == "pose")
    early = [r["kind"] for r in records[:last_pose] if r["kind"] in ("summary", "verdict")]
    if early:
        bad.append(f"{early} before the last pose")
    return bad


@pytest.fixture(scope="module")
def real_b2():
    return load(REAL_B2)


def test_the_real_b2_log_has_one_pose_per_second(real_b2):
    poses = [r for r in real_b2 if r["kind"] == "pose"]
    assert len(poses) == 180 and poses[-1]["t"] == 179.0
    assert cadence_problems(real_b2) == []


def _poses(out):
    return [r for r in out if r["kind"] == "pose"]


def _drop_one(out):
    out.remove(_poses(out)[50])


def _double_one(out):
    p = _poses(out)[50]
    out.insert(out.index(p) + 1, copy.deepcopy(p))


def _half_second(out):
    _poses(out)[50]["t"] += 0.5


def _cut_tail(out):
    for p in _poses(out)[-5:]:
        out.remove(p)


def _pose_out_of_place(out):
    p = _poses(out)[50]
    out.remove(p)
    out.insert(out.index(_poses(out)[60]), p)


def _summary_early(out):
    s = next(r for r in out if r["kind"] == "summary")
    out.remove(s)
    out.insert(out.index(_poses(out)[-1]), s)


BROKEN = {
    "a missing second": (_drop_one, "missing pose seconds [50]"),
    "a repeated second": (_double_one, "repeated pose seconds [50]"),
    "a pose at 50.5 s": (_half_second, "off the whole second"),
    "the last 5 s of poses cut": (_cut_tail, "but the run ended"),
    "a pose written 10 s late": (_pose_out_of_place, "time goes back"),
    "summary before the last pose": (_summary_early, "before the last pose"),
}


@pytest.mark.parametrize("name", BROKEN)
def test_a_broken_cadence_is_caught(real_b2, name):
    change, expect = BROKEN[name]
    out = copy.deepcopy(real_b2)
    change(out)
    bad = cadence_problems(out)
    assert any(expect in line for line in bad), f"{name}: not caught; found {bad}"


@pytest.mark.skipif(os.environ.get("RUN_B2_REAL") != "1", reason="real MuJoCo runs: set RUN_B2_REAL=1 (~3 min)")
@pytest.mark.parametrize("floor", ["B1", "B2", "B3"])
def test_fresh_real_runs(tmp_path, floor):
    pytest.importorskip("mujoco")
    _, path = run_b2.run(seed=0, out_dir=tmp_path, floor=floor)
    assert cadence_problems(load(path)) == []
