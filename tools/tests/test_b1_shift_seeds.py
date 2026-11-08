"""B1-SHIFT-SEEDS: the slab-shift recheck on B1 (tools/run_b2.py --floor B1), seeds 0-4.

Each seed runs the real L1 > ground > B1 descent, drops slab x1 on the Scout's route on B1 and needs all nine
e2e steps: the slab lands on the route, the Scout stops short of it, maps it from its own LiDAR, re-plans
around it, never enters it, reaches c1, no teleport, and a scouted route L1 > B1 exists.

Opt-in like the other real runs of tools/run_b2.py (RUN_B2_REAL=1): about 20 s of wall time per seed.

On main at the time of writing, every seed fails the five shift steps: no slab is ever dropped on B1
(run_b2.py's "no shift (route on B1 too short or never driven)"). The cause: B1's way to c1 is planned
only as "explore" routes, as c1's cell stays unknown until the Scout is nearly there, and run_b2.py drops
the slab only on an "ok" route. See the PR for the measured fix.
"""

import json
import os

import pytest

from tools.run_b2 import STEPS

SEEDS = range(5)

pytestmark = pytest.mark.skipif(os.environ.get("RUN_B2_REAL") != "1",
                                reason="real B1 runs, ~20 s each: set RUN_B2_REAL=1")


@pytest.mark.parametrize("seed", SEEDS)
def test_b1_slab_shift_recheck_passes(seed, tmp_path):
    pytest.importorskip("mujoco")
    from tools.run_b2 import run

    verdict, path = run(seed=seed, out_dir=tmp_path, floor="B1")
    assert path.name == f"b1-{seed}.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    shifts = [r for r in records if r["kind"] == "shift"]
    detail = {name: s["detail"] for name, s in verdict["steps"].items() if not s["ok"]}
    assert shifts, f"seed {seed}: no slab dropped on B1 ({detail.get(STEPS[1])})"
    assert len(shifts) == 1 and shifts[0]["level"] == "B1"
    assert verdict["failed"] == [], f"seed {seed}: {detail}"
