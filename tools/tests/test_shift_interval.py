"""SHIFT-INTERVAL: bound the single shift-to-recovery interval in real logs.

No task-specific timing contract or repeated-shift scheduler was found. Infer
recovery interval as `shift` -> measured `mapped` -> first safe `ok` route,
within run_b2's existing 3 s STOP_WINDOW (see related #233/#234 and #248/#249).
Use real B2/B3 descents and sim timestamps, never wall-clock runtime. This does
NOT prove inter-shift spacing, periodic aftershock cadence, stationary robots,
physics approval or Responder gating: the runner injects exactly one slab.
"""

import json
import math

import pytest

from tools import run_b2


def recovery_interval(records, floor):
    shifts = [(i, r) for i, r in enumerate(records) if r["kind"] == "shift"]
    assert len(shifts) == 1, shifts
    shift_index, shift = shifts[0]
    assert shift["level"] == floor
    mapped = next(((i, r) for i, r in enumerate(records)
                   if i > shift_index and r["kind"] == "mapped"), None)
    assert mapped is not None, "no measured end to the shift interval"
    mapped_index, evidence = mapped
    assert evidence["cells"] > 0, evidence
    assert evidence["sources"] and set(evidence["sources"]) <= {"lidar", "refused"}, evidence
    core = {tuple(cell) for cell in shift["core"]}
    assert core
    plans = [(i, r) for i, r in enumerate(records)
             if i > shift_index and r["kind"] == "plan"]
    assert plans, "shift interval never reached a replacement plan"
    plan_index, plan = plans[0]
    assert plan_index > mapped_index, ("plan before measured recovery", plan, evidence)
    assert plan["status"] == "ok" and plan["cells"], plan
    assert not core.intersection(tuple(cell[:2]) for cell in plan["cells"]), plan

    start, mapped_t, end = shift["t"], evidence["t"], plan["t"]
    assert all(math.isfinite(t) for t in (start, mapped_t, end))
    assert start < mapped_t <= end, (start, mapped_t, end)
    # 3 s is the existing runner response budget, not a newly invented cadence.
    assert 0 < end - start <= run_b2.STOP_WINDOW, (start, mapped_t, end)
    return start, mapped_t, end


@pytest.mark.parametrize("floor", ["B2", "B3"])
def test_real_shift_recovery_interval_fits_response_budget(tmp_path, record_property, floor):
    verdict, path = run_b2.run(seed=0, max_t=500.0, out_dir=tmp_path, floor=floor)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert verdict["failed"] == [], verdict
    start, mapped_t, end = recovery_interval(records, floor)
    for name, value in (("shift_t", start), ("mapped_t", mapped_t), ("safe_plan_t", end),
                        ("shift_to_mapped_s", mapped_t - start), ("shift_to_safe_plan_s", end - start)):
        record_property(name, value)
    summary = next(r for r in records if r["kind"] == "summary")
    assert 0 < start < summary["t"]
    assert end <= summary["t"]
    assert summary["reached"] is True and summary["final_level"] == floor, summary
