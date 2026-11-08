"""NO-TELEPORT: the Scout's logged poses in a real run_b2 log never jump, in xy, in height, or between floors.

run_b2.evaluate()'s "no teleport" step trusts one number the runner wrote itself, summary.max_jump. This
test checks the 1 Hz "pose" records in the log on their own, so a log whose poses jump fails even when its
summary claims otherwise:

  - cadence: poses start at t 0, strictly increase and are never more than 1 s apart (no gap hides a jump);
  - speed: no move between two poses beats MAX_JUMP per 0.1 s tick (0.35 m/s, run_b2's bound);
  - height: no rise or drop steeper than the sim's own MAX_RISE (a 31 deg slope) plus slack: no lift;
  - floors: the Scout leaves a floor only via "ramp" and arrives at a neighbouring floor
    (L1 > ground > B1 > B2 > B3), and the "level" records agree with the poses;
  - summary: max_jump agrees with the poses (the self-reported number is not smaller than they show).

The checked-in real B2 seed-0 log (console/tests/fixtures/b2-seed0.jsonl, from tools/run_b2.py) runs in CI.
Copies of it with planted teleports must fail. RUN_B2_REAL=1 also runs tools/run_b2.py --floor B1/B2/B3
seed 0 in MuJoCo and checks those fresh logs (about 3 min).
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
FLOORS = ("L1", "ground", "B1", "B2", "B3")
TICK = 0.1                 # run_b2's sim tick (seconds); MAX_JUMP is metres per tick
POSE_EVERY = 1.0           # run_b2 logs a pose each sim second
RISE = 0.6                 # sim.levels.MAX_RISE: floor change per metre driven
ROUND = 0.002              # positions are logged to 1 mm; two of them per step
Z_SLACK = 0.02             # sim.levels STEP_SLACK over a second of ticks, plus rounding


def teleports(records):
    """Every way the pose records break continuity, as short strings; [] means none."""
    poses = [r for r in records if r["kind"] == "pose"]
    if not poses:
        return ["no pose records"]
    bad = []
    if poses[0]["t"] != 0:
        bad.append(f"first pose at t={poses[0]['t']}, not 0")
    max_speed = run_b2.MAX_JUMP / TICK
    floor = poses[0]["level"]
    if floor not in FLOORS:
        bad.append(f"starts on {floor}, not a floor")
    for a, b in itertools.pairwise(poses):
        dt = round(b["t"] - a["t"], 3)
        where = f"t={a['t']}->{b['t']}"
        if dt <= 0:
            bad.append(f"{where}: time does not advance")
            continue
        if dt > POSE_EVERY + 1e-6:
            bad.append(f"{where}: {dt} s without a pose")
        move = math.dist(a["pos"], b["pos"])
        if move > max_speed * dt + ROUND:
            bad.append(f"{where}: moved {move:.3f} m in {dt} s (max {max_speed * dt:.3f})")
        flat = math.dist(a["pos"][:2], b["pos"][:2])
        rise = abs(b["pos"][2] - a["pos"][2])
        if rise > RISE * flat + Z_SLACK:
            bad.append(f"{where}: height changed {rise:.3f} m over {flat:.3f} m driven")
        if b["level"] != a["level"]:
            if a["level"] != "ramp" and b["level"] != "ramp":
                bad.append(f"{where}: {a['level']} -> {b['level']} without a ramp")
            if b["level"] not in FLOORS + ("ramp",):
                bad.append(f"{where}: unknown level {b['level']}")
            elif b["level"] != "ramp":
                if floor in FLOORS and abs(FLOORS.index(b["level"]) - FLOORS.index(floor)) > 1:
                    bad.append(f"{where}: {floor} -> {b['level']} skips a floor")
                floor = b["level"]
    pose_floors = [poses[0]["level"]] + [b["level"] for a, b in itertools.pairwise(poses)
                                         if b["level"] != a["level"] and b["level"] != "ramp"]
    logged = [r["level"] for r in records if r["kind"] == "level"]
    squeezed = [lv for i, lv in enumerate(pose_floors) if i == 0 or lv != pose_floors[i - 1]]
    if logged != squeezed:
        bad.append(f"level records {logged} disagree with the poses {squeezed}")
    summary = next((r for r in records if r["kind"] == "summary"), None)
    if summary is None or summary.get("max_jump") is None:
        bad.append("no summary max_jump")
    else:
        # Over dt seconds the Scout makes dt/TICK ticks, none longer than max_jump.
        worst = max((math.dist(a["pos"], b["pos"]) - ROUND) / ((b["t"] - a["t"]) / TICK)
                    for a, b in itertools.pairwise(poses) if b["t"] > a["t"]) if len(poses) > 1 else 0.0
        if worst > summary["max_jump"] + 1e-4:
            bad.append(f"summary max_jump {summary['max_jump']} is below the poses' {worst:.4f} m/tick")
    return bad


def load(path):
    return [json.loads(line) for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture(scope="module")
def real_b2():
    return load(REAL_B2)


def test_the_real_b2_log_has_no_teleport(real_b2):
    poses = [r for r in real_b2 if r["kind"] == "pose"]
    assert len(poses) > 100 and poses[-1]["level"] == "B2"
    assert teleports(real_b2) == []
    assert run_b2.evaluate(real_b2)["steps"]["no teleport"]["ok"]


def planted(records, change):
    out = copy.deepcopy(records)
    poses = [r for r in out if r["kind"] == "pose"]
    change(poses, out)
    return out


def _mid(poses, level):
    """A pose in the middle of the stretch spent on `level`, and its index among the poses."""
    on = [i for i, p in enumerate(poses) if p["level"] == level]
    return on[len(on) // 2]


def _xy_jump(poses, _):
    i = _mid(poses, "B1")
    for p in poses[i:]:              # from here on the trace is shifted 1 m: one jump, then continuous
        if p["level"] != "B1":
            break
        p["pos"][0] += 1.0


def _lift(poses, _):
    i = _mid(poses, "ground")       # same xy, the next floor down: a lift, not a ramp
    p = poses[i]
    p["pos"][2] -= 0.6
    p["level"] = "B1"


def _skip_floor(poses, out):
    # Relabel the ground stretch as B1, so the Scout goes L1 -> ramp -> B1 with no ground in between.
    for p in poses:
        if p["level"] == "ground":
            p["level"] = "B1"
    levels = [r for r in out if r["kind"] == "level"]
    out.remove(next(r for r in levels if r["level"] == "ground"))


def _gap(poses, out):
    # Drop four seconds of poses: each remaining step is slow enough, but nobody saw the Scout in between.
    i = _mid(poses, "B1")
    for p in poses[i:i + 4]:
        out.remove(p)


def _summary_lies(_poses, out):
    s = next(r for r in out if r["kind"] == "summary")
    s["max_jump"] = 0.001


def _no_ramp(poses, out):
    # The first ramp stretch relabelled as L1: the Scout is on L1 one second, on ground the next.
    first = next(i for i, p in enumerate(poses) if p["level"] == "ramp")
    j = first
    while poses[j]["level"] == "ramp":
        poses[j]["level"] = "L1"
        j += 1


PLANTS = {
    "1 m sideways jump on B1": (_xy_jump, "moved"),
    "lift from ground to B1 in place": (_lift, "height changed"),
    "L1 to B1 with no ground": (_skip_floor, "skips a floor"),
    "4 s of poses missing": (_gap, "without a pose"),
    "summary max_jump below the poses": (_summary_lies, "summary max_jump"),
    "floor change without a ramp": (_no_ramp, "without a ramp"),
}


@pytest.mark.parametrize("name", PLANTS)
def test_a_planted_teleport_is_caught(real_b2, name):
    change, expect = PLANTS[name]
    bad = teleports(planted(real_b2, change))
    assert any(expect in line for line in bad), f"{name}: not caught; found {bad}"


@pytest.mark.skipif(os.environ.get("RUN_B2_REAL") != "1", reason="real MuJoCo runs: set RUN_B2_REAL=1 (~3 min)")
@pytest.mark.parametrize("floor", ["B1", "B2", "B3"])
def test_fresh_real_runs_have_no_teleport(tmp_path, floor):
    pytest.importorskip("mujoco")
    _, path = run_b2.run(seed=0, out_dir=tmp_path, floor=floor)
    records = load(path)
    assert [r for r in records if r["kind"] == "pose"][-1]["level"] == floor
    assert teleports(records) == []
