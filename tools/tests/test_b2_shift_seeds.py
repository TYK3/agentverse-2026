"""B2-SHIFT-SEEDS: the slab-shift recheck on B2 (tools/run_b2.py --floor B2), seeds 0-4.

Each seed runs the real L1 > ground > B1 > B2 descent, drops slab x1 on the Scout's planned route to c2
on B2 and needs all nine e2e steps: the slab lands on the route, the Scout stops short of it, maps it from
its own measurements, re-plans around it, never enters it, reaches c2, no teleport, and a scouted route
L1 > B2 exists. The log is read back as well, so the checks are on what the run recorded, not only on
the verdict: one shift, on B2, a stop or re-plan inside STOP_WINDOW, a fresh "mapped" record after the
shift, and every planned path after the shift clear of the slab's core cells.

Opt-in like the other real runs of tools/run_b2.py (RUN_B2_REAL=1): about 20 s of wall time per seed.

Measured on main (8411ab5): all five seeds pass 9/9, and the five run logs are byte-identical; the seed
does not change anything in this scene yet, so this guards the recheck against a seed starting to matter.
"""

import json
import os

import pytest

from tools.run_b2 import STEPS, STOP_WINDOW

SEEDS = range(5)

pytestmark = pytest.mark.skipif(os.environ.get("RUN_B2_REAL") != "1",
                                reason="real B2 runs, ~20 s each: set RUN_B2_REAL=1")


@pytest.mark.parametrize("seed", SEEDS)
def test_b2_slab_shift_recheck_passes(seed, tmp_path):
    pytest.importorskip("mujoco")
    from tools.run_b2 import run

    verdict, path = run(seed=seed, out_dir=tmp_path, floor="B2")
    assert path.name == f"b2-{seed}.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    detail = {name: s["detail"] for name, s in verdict["steps"].items() if not s["ok"]}

    # The slab was dropped once, on B2, on the route the Scout was driving.
    shifts = [r for r in records if r["kind"] == "shift"]
    assert shifts, f"seed {seed}: no slab dropped on B2 ({detail.get(STEPS[1])})"
    assert len(shifts) == 1 and shifts[0]["level"] == "B2"
    shift = shifts[0]
    before = [r for r in records if r["kind"] == "plan" and r["t"] <= shift["t"]]
    assert before and before[-1]["status"] == "ok", f"seed {seed}: shift not on a planned route to c2"
    core = {tuple(c) for c in shift["core"]}
    after = [r for r in records if r["t"] >= shift["t"]]

    # The Scout stopped (or turned away) inside the stop window.
    stopped = [r for r in after if r["t"] <= shift["t"] + STOP_WINDOW and (
        (r["kind"] == "pose" and r["state"] in ("blocked", "arrived", "idle"))
        or (r["kind"] == "plan" and r["t"] > shift["t"]))]
    assert stopped, f"seed {seed}: kept driving after the shift ({detail.get(STEPS[2])})"

    # Fresh recheck: the slab got into the map from the Scout's own sensing, after the shift.
    mapped = [r for r in after if r["kind"] == "mapped"]
    assert mapped and mapped[0]["cells"] > 0, f"seed {seed}: slab never mapped ({detail.get(STEPS[3])})"

    # Every path planned after the shift avoids the slab, and the Scout never stood in it.
    replans = [r for r in after if r["kind"] == "plan" and r["cells"] and r["t"] > shift["t"]]
    assert replans, f"seed {seed}: no re-plan after the shift"
    assert all(not core & {tuple(c[:2]) for c in r["cells"]} for r in replans), f"seed {seed}: route through slab"
    assert not [r for r in after if r["kind"] == "pose" and tuple(r["cell"][:2]) in core]

    # Still a rescue: c2 reached on B2, and the run's own verdict is 9/9.
    summary = next(r for r in records if r["kind"] == "summary")
    assert summary["reached"] is True and summary["final_level"] == "B2", f"seed {seed}: {detail}"
    assert verdict["failed"] == [], f"seed {seed}: {detail}"
    assert len(verdict["passed"]) == len(STEPS)
