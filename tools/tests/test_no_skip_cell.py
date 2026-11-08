"""NO-SKIP-CELL: every route in a real run log is a connected chain of grid cells, no cell skipped.

tools/run_b2.py logs each plan's cells ([i, j, k], 0.05 m grid, k = height / 0.05). A route that jumps over a
cell could pass through one that nothing checked. Each step must therefore go to one of the 8 plan-view
neighbours (Chebyshev distance exactly 1: no skip, no repeat), and k may change by at most one per step,
only while the step also moves in plan view (a ramp, never a vertical jump in place). A route also starts
where the Scout stood when it was planned: within one cell of the last pose's cell, plus the cells it can
have driven since that pose (poses are logged at 1 Hz).

The real B2 run (seed 0, about 30 s) runs by default; the B3 run is opt-in (RUN_B2_REAL=1, about 60 s),
like tools/tests/test_run_b2.py. The checker itself is tested on planted skips.
"""

import itertools
import json
import math
import os

import pytest

RES = 0.05             # metres per cell
SPEED = 0.3            # m/s, the Scout's top speed (sim/world.py): poses are logged at 1 Hz


def skips(cells):
    """[(index, reason)] for every step of a route that is not to a neighbouring cell."""
    out = []
    for n, (a, b) in enumerate(itertools.pairwise(cells)):
        xy = max(abs(a[0] - b[0]), abs(a[1] - b[1]))
        dk = abs(a[2] - b[2])
        if xy == 0 and dk == 0:
            out.append((n, f"repeats {a}"))
        elif xy > 1:
            out.append((n, f"skips from {a} to {b}"))
        elif dk > 1 or (dk and xy == 0):
            out.append((n, f"jumps height from {a} to {b}"))
    return out


def test_the_checker_finds_planted_skips():
    good = [[0, 0, 0], [1, 0, 0], [2, 1, 0], [3, 1, -1], [4, 2, -2]]
    assert skips(good) == []
    assert skips([[0, 0, 0], [2, 0, 0]]) == [(0, "skips from [0, 0, 0] to [2, 0, 0]")]
    assert skips([[0, 0, 0], [1, 2, 0]])[0][1].startswith("skips")
    assert skips([[0, 0, 0], [0, 0, 0]]) == [(0, "repeats [0, 0, 0]")]
    assert skips([[0, 0, 0], [0, 0, -1]])[0][1].startswith("jumps height")      # down in place
    assert skips([[0, 0, 0], [1, 0, -2]])[0][1].startswith("jumps height")      # two levels in one step


def run(floor):
    pytest.importorskip("mujoco")
    from tools import run_b2

    def go(tmp_path):
        _, path = run_b2.run(seed=0, out_dir=tmp_path, floor=floor)
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return go


@pytest.fixture(scope="module")
def b2(tmp_path_factory):
    return run("B2")(tmp_path_factory.mktemp("b2"))


@pytest.fixture(scope="module")
def b3(tmp_path_factory):
    if os.environ.get("RUN_B2_REAL") != "1":
        pytest.skip("full B3 run: set RUN_B2_REAL=1")
    return run("B3")(tmp_path_factory.mktemp("b3"))


def routes(records):
    return [r for r in records if r["kind"] == "plan" and r.get("cells")]


def check_log(records):
    plans = routes(records)
    assert len(plans) >= 10, f"only {len(plans)} routes in the log"
    assert any(r["status"] == "ok" for r in plans), "no verified route at all"
    bad = {r["t"]: skips(r["cells"]) for r in plans if skips(r["cells"])}
    assert not bad, f"routes with skipped cells (t: steps): {dict(list(bad.items())[:3])}"
    pose = None
    for r in records:
        if r["kind"] == "pose":
            pose = r
        elif r["kind"] == "plan" and r.get("cells") and pose is not None:
            here, start = pose["cell"], r["cells"][0]
            slack = 1 + math.ceil(SPEED * (r["t"] - pose["t"]) / RES)
            off = max(abs(start[0] - here[0]), abs(start[1] - here[1]))
            assert off <= slack, f"route at {r['t']} s starts {off} cells from the Scout ({here} at {pose['t']} s)"


def test_every_route_in_a_real_b2_log_is_connected(b2):
    check_log(b2)


def test_every_route_in_a_real_b3_log_is_connected(b3):
    check_log(b3)


def test_ramp_routes_change_floor_one_level_at_a_time(b2):
    ramp_steps = [(a, b) for r in routes(b2) for a, b in itertools.pairwise(r["cells"]) if a[2] != b[2]]
    assert ramp_steps, "no route in the B2 log goes down a ramp"
    assert all(abs(a[2] - b[2]) == 1 for a, b in ramp_steps)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
