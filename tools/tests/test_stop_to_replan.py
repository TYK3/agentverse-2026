"""STOP-TO-REPLAN: after a slab shift the Scout stops what it was doing and plans anew, fast, around it.

Real runs of tools/run_b2.py (seed 0) on B2 and B3: the Scout's closed-loop descent, a slab dropped on its
route to the casualty, the stop and the recheck. From each run's jsonl:
  - the first plan after the shift comes within REPLAN_WITHIN sim seconds (measured 2026-11-08: B2 0.1 s,
    B3 0.2 s);
  - it is a new plan, not the one in force when the slab landed: a different target;
  - its cells avoid the slab, and the Scout never stands inside the slab between the shift and that plan.
"""

import json

import pytest

from tools.run_b2 import run

pytest.importorskip("mujoco")

REPLAN_WITHIN = 1.0


@pytest.fixture(scope="module", params=["B2", "B3"])
def log(request, tmp_path_factory):
    _, path = run(seed=0, out_dir=tmp_path_factory.mktemp(request.param.lower()), floor=request.param)
    return request.param, [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def around_shift(rows):
    shift = next(r for r in rows if r["kind"] == "shift")
    before = [r for r in rows if r["kind"] == "plan" and r["t"] <= shift["t"]][-1]
    after = next(r for r in rows if r["kind"] == "plan" and r["t"] > shift["t"])
    return shift, before, after


def test_a_new_plan_follows_the_shift_quickly(log):
    floor, rows = log
    shift, _, after = around_shift(rows)
    took = after["t"] - shift["t"]
    assert 0 < took <= REPLAN_WITHIN, f"{floor}: first plan {took:.1f} s after the shift"


def test_the_new_plan_has_a_new_target(log):
    floor, rows = log
    _, before, after = around_shift(rows)
    assert after["target"] != before["target"], f"{floor}: still heading for {before['target']}"


def test_the_new_plan_avoids_the_slab_and_the_scout_never_entered_it(log):
    floor, rows = log
    shift, _, after = around_shift(rows)
    core = {tuple(c) for c in shift["core"]}
    assert not core & {tuple(c[:2]) for c in after["cells"]}, f"{floor}: re-plan crosses the slab"
    inside = [r for r in rows if r["kind"] == "pose" and shift["t"] <= r["t"] <= after["t"]
              and tuple(r["cell"][:2]) in core]
    assert inside == []
