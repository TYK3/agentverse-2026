"""DESCENT-TIME: how long the real closed-loop descent (sim.demo_descent) takes to reach each floor.

The Scout starts on L1 and finds its own way down (L1 > ground > B1 > B2 > B3 on ramps R2, R1, R3, R4).
For each target floor the test reads the run's own per-tick trace (t, x, y, z) and takes the first sim time
the Scout rides at each floor's height, then checks:
  - the Scout reaches the casualty on the target floor inside the floor's sim-time budget,
  - it arrives on every floor on the way, in order, each inside its budget, and time never goes back,
  - the run ends when the Scout arrives (the summary time is the last tick of the trace),
  - the same run gives the same times (no wall clock, no randomness).

Budgets are about 1.5x the sim seconds measured on main (8411ab5), shown as "today" beside each.
Times are sim seconds, not wall time. B1 runs by default (about 10 s of wall time); the B2 and B3
descents are opt-in like the other real runs (RUN_B2_REAL=1): about 20 s and 40 s of wall time.
"""

import itertools
import os

import pytest

FLOOR_Z = {"L1": 0.6, "ground": 0.0, "B1": -0.6, "B2": -1.2, "B3": -1.8}
ORDER = ["L1", "ground", "B1", "B2", "B3"]
TOL = 0.005                                    # metres: on a floor, not on a ramp passing near it

# Sim-second budgets: first arrival on each floor, and the casualty reached ("goal").
BUDGET = {
    "B1": {"ground": 35.0, "B1": 125.0, "goal": 135.0},                       # today 22.0, 81.1, 88.7
    "B2": {"ground": 35.0, "B1": 125.0, "B2": 235.0, "goal": 265.0},          # today 22.0, 81.1, 155.4, 176.4
    "B3": {"ground": 35.0, "B1": 125.0, "B2": 215.0, "B3": 325.0, "goal": 345.0},
}                                                                             # B3 today 22.0, 66.2, 143.1, 217.4, 228.9

real = pytest.mark.skipif(os.environ.get("RUN_B2_REAL") != "1", reason="real descent: set RUN_B2_REAL=1")


def arrivals(trace, ride):
    """{floor: first sim time the trace rides at that floor's height} for the floors it reaches."""
    out = {}
    for t, _x, _y, z in trace:
        for name, fz in FLOOR_Z.items():
            if name not in out and abs(z - (fz + ride)) < TOL:
                out[name] = round(t, 1)
    return out


def check(run, floor):
    from sim.levels import RIDE

    assert run["reached"] is True, run["log"][-3:]
    want = ORDER[:ORDER.index(floor) + 1]
    assert run["levels"] == want
    got = arrivals(run["trace"], RIDE)
    assert list(got) == want, got                                  # every floor on the way, in order
    times = [got[n] for n in want]
    assert times == sorted(times) and len(set(times)) == len(times), got
    ts = [row[0] for row in run["trace"]]
    assert all(b > a for a, b in itertools.pairwise(ts))    # sim time never goes back
    assert run["t"] == pytest.approx(ts[-1], abs=0.05)             # ends on arrival, not at max_t
    over = {n: (got.get(n, run["t"]), b) for n, b in BUDGET[floor].items()
            if (run["t"] if n == "goal" else got[n]) > b}
    assert not over, f"{floor}: over budget (sim s, budget) {over}"
    return got


def test_arrivals_reads_first_time_on_each_floor_height():
    ride = 0.075
    trace = [(0.0, 0, 0, 0.675), (5.0, 0, 0, 0.4), (10.0, 0, 0, 0.075), (10.1, 0, 0, 0.075),
             (20.0, 0, 0, -0.3), (30.0, 0, 0, -0.525)]
    assert arrivals(trace, ride) == {"L1": 0.0, "ground": 10.0, "B1": 30.0}
    assert arrivals([(0.0, 0, 0, 0.678)], ride) == {"L1": 0.0}    # 3 mm off: still L1
    assert arrivals([(0.0, 0, 0, 0.3)], ride) == {}               # mid-ramp is no floor


def test_budgets_grow_with_depth_and_cover_each_floor_on_the_way():
    for floor, b in BUDGET.items():
        want = ORDER[1:ORDER.index(floor) + 1]
        assert list(b) == want + ["goal"]
        vals = list(b.values())
        assert vals == sorted(vals)
    assert BUDGET["B1"]["goal"] < BUDGET["B2"]["goal"] < BUDGET["B3"]["goal"]


@pytest.fixture(scope="module")
def descent_b1():
    pytest.importorskip("mujoco")
    from sim.demo_descent import run
    return run(max_t=400.0, floor="B1")


def test_b1_descent_is_inside_its_time_budget(descent_b1):
    check(descent_b1, "B1")


def test_b1_descent_time_is_the_same_on_a_second_run(descent_b1):
    from sim.demo_descent import run
    from sim.levels import RIDE

    again = run(max_t=400.0, floor="B1")
    assert again["t"] == descent_b1["t"] and again["plans"] == descent_b1["plans"]
    assert arrivals(again["trace"], RIDE) == arrivals(descent_b1["trace"], RIDE)


@real
@pytest.mark.parametrize("floor", ["B2", "B3"])
def test_deeper_descent_is_inside_its_time_budget(floor):
    pytest.importorskip("mujoco")
    from sim.demo_descent import run

    got = check(run(max_t=600.0, floor=floor), floor)
    assert got["ground"] < got["B1"] < got[floor]
