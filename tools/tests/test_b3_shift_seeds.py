"""B3-SHIFT-SEEDS: the slab-shift recheck on B3 (tools/run_b2.py --floor B3), seeds 0-4.

Each seed runs the real L1 > ground > B1 > B2 > B3 descent, drops a slab on the Scout's planned route
on B3 and needs all nine e2e steps. Beyond the verdict it reads the run log itself: exactly one shift,
on B3; the Scout stops (or turns away) after it and before any re-plan; the slab is mapped from the
Scout's own measurements; every route planned after the shift keeps out of the slab's footprint; and
the run ends at c3 on B3.

Opt-in like the other real runs of tools/run_b2.py (RUN_B2_REAL=1): about 40 s of wall time per seed.
"""

import json
import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_B2_REAL") != "1",
                                reason="real B3 runs, ~40 s each: set RUN_B2_REAL=1")

SEEDS = range(5)


@pytest.mark.parametrize("seed", SEEDS)
def test_b3_slab_shift_recheck_passes(seed, tmp_path):
    pytest.importorskip("mujoco")
    from tools.run_b2 import STEPS, run

    verdict, path = run(seed=seed, out_dir=tmp_path, floor="B3")
    assert path.name == f"b3-{seed}.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    detail = {name: s["detail"] for name, s in verdict["steps"].items() if not s["ok"]}
    assert verdict["failed"] == [], f"seed {seed}: {detail}"
    assert verdict["passed"] == list(STEPS)

    shifts = [r for r in records if r["kind"] == "shift"]
    assert len(shifts) == 1 and shifts[0]["level"] == "B3", shifts
    t_shift = shifts[0]["t"]
    core = {tuple(c[:2]) for c in shifts[0]["core"]}
    after = [r for r in records if r["t"] >= t_shift]

    mapped = [r for r in after if r["kind"] == "mapped"]
    assert mapped and mapped[0]["cells"] > 0 and mapped[0]["sources"], "slab not mapped from the Scout's scans"

    plans = [r for r in records if r["kind"] == "plan" and r["t"] > t_shift]
    assert plans, "no re-plan after the shift"
    for p in plans:
        assert not core & {tuple(c[:2]) for c in p["cells"]}, f"route at t={p['t']} enters the slab"

    summary = next(r for r in records if r["kind"] == "summary")
    assert summary["reached"] is True and summary["final_level"] == "B3" and summary["floor"] == "B3"
