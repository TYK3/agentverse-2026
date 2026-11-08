"""PLAN-AFTER-RECHECK: every post-shift path follows the measured recheck.

Interpretation follows RECHECK-PLAN-NEW (#297): tools.run_b2's `mapped` record
is the recheck, meaning the real Scout measured occupied slab cells. A new plan
must not precede that evidence, and every later path must avoid the slab core.
This is a real L1-to-B2 sim/perception/planner descent with a slab shift, not a
fake log. The runner does not call World.verify or dispatch Responder actions;
physics-completion and Responder-move gating are NOT proven by this log test.
"""

import json

from tools import run_b2


def assert_plans_follow_measured_recheck(records):
    shifts = [(i, r) for i, r in enumerate(records) if r["kind"] == "shift"]
    assert len(shifts) == 1, shifts
    shift_index, shift = shifts[0]
    assert shift["level"] == "B2"
    rechecks = [(i, r) for i, r in enumerate(records)
                if i > shift_index and r["kind"] == "mapped"]
    assert rechecks, "no post-shift measured recheck"
    recheck_index, recheck = rechecks[0]
    assert recheck["t"] >= shift["t"]
    assert recheck["cells"] > 0, recheck
    assert set(recheck["sources"]) & {"lidar", "refused"}, recheck

    # Inspect ALL post-shift plans: selecting only plans after `mapped` would
    # silently ignore an unsafe earlier plan. Record order resolves equal t.
    plans = [(i, r) for i, r in enumerate(records)
             if i > shift_index and r["kind"] == "plan"]
    assert plans, "no post-shift plan"
    core = {tuple(cell) for cell in shift["core"]}
    assert core
    for index, plan in plans:
        assert index > recheck_index, ("plan before measured recheck", plan, recheck)
        assert plan["t"] >= recheck["t"], (plan, recheck)
        assert plan["cells"], plan
        assert not core.intersection(tuple(cell[:2]) for cell in plan["cells"]), plan


def test_real_b2_plans_wait_for_recheck_and_avoid_shifted_slab(tmp_path):
    verdict, path = run_b2.run(seed=0, max_t=500.0, out_dir=tmp_path, floor="B2")
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert verdict["failed"] == [], verdict
    assert [r["level"] for r in records if r["kind"] == "level"] == [
        "L1", "ground", "B1", "B2"
    ]
    assert_plans_follow_measured_recheck(records)
    summary = next(r for r in records if r["kind"] == "summary")
    assert summary["reached"] is True and summary["final_level"] == "B2", summary
