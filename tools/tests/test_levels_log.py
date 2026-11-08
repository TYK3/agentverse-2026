"""LEVELS-LIVE-3: the chained run's log (tools/run_levels.py, runs/levels-<seed>.jsonl) is well formed and
consistent with itself: what each record carries, time order, pose cadence, poses on the floor their level
names, legs in order, plans only for the leg in progress, steps = evaluate(log), and the same seed gives
the same log. evaluate()'s own pass/fail rules are tested in tools/tests/test_run_levels.py (#192).

One real run (about 25 s wall time) is shared by the module; the determinism check uses two short runs.
The runs need mujoco, which CI's tools job does not install, so the module skips there (as the real runs in
test_run_b2 / test_run_levels do); run it locally with the sim requirements.
"""

import itertools
import json
import math

import pytest

pytest.importorskip("mujoco")

from tools import run_levels

FLOOR_Z = {"L1": 0.6, "ground": 0.0, "B1": -0.6, "B2": -1.2, "B3": -1.8}   # sim/scenes/levels.xml floor tops
ORIGIN_Z = (0.0, 0.12)        # pose z above the floor it stands on (Scout origin 0.075 m, plus settling)
KEYS = {
    "meta": {"seed", "legs", "source"},
    "level": {"level"},
    "plan": {"leg", "why", "target", "state"},
    "pose": {"level", "pos"},
    "leg": {"floor", "casualty", "reached"},
    "summary": {"max_jump", "responder_route", "final_pos", "plans"},
    "step": {"name", "ok", "detail"},
}


@pytest.fixture(scope="module")
def log():
    records = run_levels.run(seed=0)
    # what main() writes and a reader gets back: one compact JSON object per line
    text = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records)
    return [json.loads(line) for line in text.splitlines()]


def of(log, kind):
    return [r for r in log if r["kind"] == kind]


def test_every_record_has_its_kind_fields_and_a_sim_time(log):
    assert log[0]["kind"] == "meta" and log[0]["seed"] == 0 and log[0]["legs"] == list(run_levels.LEGS)
    for r in log:
        assert r["kind"] in KEYS, r
        assert KEYS[r["kind"]] <= set(r), r
        assert isinstance(r["t"], float) and r["t"] >= 0
    assert len(of(log, "meta")) == 1 and len(of(log, "summary")) == 1


def test_time_never_goes_back_and_the_verdict_closes_the_log(log):
    ts = [r["t"] for r in log]
    assert ts == sorted(ts)
    kinds = [r["kind"] for r in log]
    n = len(run_levels.steps())
    assert kinds[-n:] == ["step"] * n and kinds[-n - 1] == "summary"


def test_poses_are_about_one_hertz_and_never_jump(log):
    poses = of(log, "pose")
    assert len(poses) >= int(log[-1]["t"]) - 1                      # one a second for the whole run
    gaps = [b["t"] - a["t"] for a, b in itertools.pairwise(poses)]
    assert max(gaps) <= 1.15 and min(gaps) >= 0.85
    speed = max(math.dist(a["pos"], b["pos"]) / (b["t"] - a["t"]) for a, b in itertools.pairwise(poses))
    assert speed <= 10 * run_levels.MAX_JUMP                         # 0.35 m/s: driving, never a teleport


def test_each_pose_stands_on_the_floor_its_level_names(log):
    for p in of(log, "pose"):
        if p["level"] == "ramp":
            continue
        above = p["pos"][2] - FLOOR_Z[p["level"]]
        assert ORIGIN_Z[0] <= above <= ORIGIN_Z[1], p
    seen = {p["level"] for p in of(log, "pose")}
    assert set(run_levels.ORDER) <= seen                             # it was really on every floor


def test_levels_and_legs_come_in_order_and_each_leg_ends_on_its_floor(log):
    assert [r["level"] for r in of(log, "level")] == run_levels.ORDER
    legs = of(log, "leg")
    assert [r["floor"] for r in legs] == list(run_levels.LEGS)
    assert [r["casualty"] for r in legs] == [run_levels.CASUALTY[f] for f in run_levels.LEGS]
    assert all(r["reached"] for r in legs)
    first_on = {r["level"]: r["t"] for r in of(log, "level")}
    for leg in legs:
        assert first_on[leg["floor"]] <= leg["t"]                    # reached a floor only after getting there
    end = of(log, "summary")[0]["final_pos"]
    assert end[2] - FLOOR_Z["B3"] == pytest.approx(0.075, abs=0.05)


def test_plans_belong_to_the_leg_in_progress(log):
    pending = list(run_levels.LEGS)                                  # file order: a leg record closes its leg
    for r in log:
        if r["kind"] == "leg":
            assert r["floor"] == pending.pop(0)
        elif r["kind"] == "plan":
            assert r["leg"] == pending[0], r
            assert len(r["target"]) == 3 and r["why"] in {"route", "explore", "probe"}
    assert of(log, "summary")[0]["plans"] == len(of(log, "plan"))


def test_the_logged_steps_are_what_evaluate_says_about_the_log(log):
    body = [r for r in log if r["kind"] != "step"]
    verdict = run_levels.evaluate(body)
    logged = [(r["name"], r["ok"], r["detail"]) for r in of(log, "step")]
    assert logged == verdict["steps"]
    assert verdict["failed"] == []


def test_the_same_seed_gives_the_same_log():
    a = run_levels.run(seed=1, max_t=20.0)
    b = run_levels.run(seed=1, max_t=20.0)
    assert len(of(a, "pose")) >= 15
    assert a == b
