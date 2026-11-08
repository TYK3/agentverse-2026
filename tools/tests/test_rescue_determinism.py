"""RESCUE-DETERMINISM: the same seed gives the same rescue log, byte for byte (ref #31).

The run is tools/run_b2.py on B2: the Scout's closed-loop descent from L1, a slab landing on its route
to c2, the stop and the recheck. (Not B1: there the route to c1 is only found within 0.72 m of it, too
short for the runner to drop a slab, so a B1 run has no shift to compare.) That loop ticks the sim
itself and has no wall clock, so a seed fixes everything it does. (The hub-wired real-lane runs,
run_rescue.py and demo60.py, are not deterministic yet: lanes there still time themselves on the
wall clock, see #167.)
"""

import json

import pytest

from tools.run_b2 import run  # imports mujoco only inside run()

pytest.importorskip("mujoco")


@pytest.fixture(scope="module")
def two_runs(tmp_path_factory):
    out = []
    for name in ("a", "b"):
        d = tmp_path_factory.mktemp(name)
        verdict, path = run(seed=3, out_dir=d, floor="B2")
        out.append((verdict, path))
    return out


def test_same_seed_same_log_byte_for_byte(two_runs):
    (_, a), (_, b) = two_runs
    assert a.name == b.name == "b2-3.jsonl"
    assert a.read_bytes() == b.read_bytes()


def test_same_seed_same_verdict_and_it_passes(two_runs):
    (va, _), (vb, _) = two_runs
    assert va == vb
    assert va["failed"] == [], va["steps"]


def test_the_log_has_the_shift_and_the_recheck(two_runs):
    _, path = two_runs[0]
    kinds = [json.loads(line)["kind"] for line in path.read_text(encoding="utf-8").splitlines()]
    assert {"level", "pose", "plan", "shift", "mapped", "summary", "verdict"} <= set(kinds)
    assert kinds.count("shift") == 1
    assert kinds.index("shift") < kinds.index("mapped") < kinds.index("summary")
