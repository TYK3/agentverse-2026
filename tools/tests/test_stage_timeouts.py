"""STAGE-TIMEOUTS: each stage of a real B2 rescue finishes within its time budget, and a run that runs out
of time ends cleanly with the unfinished stages failed.

The run is tools/run_b2.py --floor B2 (seed 0): the Scout's closed-loop descent L1 -> ground -> B1 -> B2,
a slab dropped on its route to c2, the stop, the recheck, c2 reached. Times are sim seconds from the
run's own jsonl. Budgets are about 1.5x the stage times measured on 2026-11-08 (in brackets), except the
recheck, which must be fast in absolute terms:
  L1 -> ground 35 s [21.6], ground -> B1 90 s [58.5], B1 -> B2 115 s [75.2], on B2 -> slab shift 40 s [18.3],
  shift -> slab mapped 2 s [0.1], mapped -> c2 reached 15 s [5.6], whole run 270 s [179.3].
"""

import json

import pytest

from tools.run_b2 import STEPS, run

pytest.importorskip("mujoco")

BUDGETS = [            # (from stage, to stage, seconds)
    ("L1", "ground", 35.0),
    ("ground", "B1", 90.0),
    ("B1", "B2", 115.0),
    ("B2", "shift", 40.0),
    ("shift", "mapped", 2.0),
    ("mapped", "reached", 15.0),
]
TOTAL = 270.0
CUT = 60.0             # sim seconds for the run that must time out cleanly


def stage_times(path):
    """{stage: first sim time}: each level reached, the shift, the slab mapped, c2 reached."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        key = {"level": r.get("level"), "shift": "shift", "mapped": "mapped"}.get(r["kind"])
        if r["kind"] == "summary" and r.get("reached"):
            key = "reached"
        if key and key not in out:
            out[key] = r["t"]
    return out


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    return run(seed=0, out_dir=tmp_path_factory.mktemp("full"), floor="B2")


@pytest.fixture(scope="module")
def cut(tmp_path_factory):
    return run(seed=0, out_dir=tmp_path_factory.mktemp("cut"), floor="B2", max_t=CUT)


@pytest.mark.parametrize("start,end,budget", BUDGETS, ids=[f"{a}->{b}" for a, b, _ in BUDGETS])
def test_each_stage_finishes_within_its_budget(full, start, end, budget):
    _, path = full
    t = stage_times(path)
    assert start in t and end in t, f"stage {start} or {end} never happened: {t}"
    took = t[end] - t[start]
    assert 0 <= took <= budget, f"{start} -> {end} took {took:.1f} s (budget {budget} s)"


def test_the_whole_rescue_fits_its_budget_and_passes(full):
    verdict, path = full
    t = stage_times(path)
    assert t["reached"] <= TOTAL
    assert verdict["failed"] == [], verdict["steps"]


def test_a_run_out_of_time_ends_cleanly_with_the_unfinished_stages_failed(cut):
    verdict, path = cut
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [r["kind"] for r in records][-2:] == ["summary", "verdict"]        # it still writes its ending
    summary = records[-2]
    assert summary["reached"] is False
    assert max(r["t"] for r in records) <= CUT + 0.2                           # it stopped at the limit
    failed = set(verdict["failed"])
    assert {STEPS[0], STEPS[1], STEPS[5], STEPS[8]} <= failed                  # descent, shift, reach, route
    assert STEPS[7] not in failed                                              # what it did, it did right
