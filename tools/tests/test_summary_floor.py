"""SUMMARY-FLOOR: a full real rescue log names its target floor, and that floor is what the run did.

#223 covers short (0.2 s) runs: summary.floor is written and validates. This covers whole runs of
tools/run_b2.py on B1 and B2 (the real closed-loop descent, seed 0):
  - every line of the real log validates against coord/run_log_schema.json;
  - summary.floor is the floor asked for, and the level the Scout finished on;
  - the scouted-map route in the summary reaches that floor's k (B1 -12, B2 -24);
  - evaluate() reads summary.floor: the same B1 log with floor removed is judged as a B2 run (the
    documented default for logs older than --floor) and fails its descent and route steps.
The B1 verdict itself is not asserted here: whether B1 gets its slab is #222's change.
"""

import json

import pytest

from tools.run_b2 import FLOOR_K, STEPS, evaluate, run
from tools.tests.test_run_log_schema import line_valid

pytest.importorskip("mujoco")


@pytest.fixture(scope="module", params=["B1", "B2"])
def real(request, tmp_path_factory):
    floor = request.param
    _, path = run(seed=0, out_dir=tmp_path_factory.mktemp(floor.lower()), floor=floor)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return floor, path, rows


def summary(rows):
    return next(r for r in rows if r["kind"] == "summary")


def test_every_line_of_the_real_log_validates(real):
    floor, path, rows = real
    assert path.name == f"{floor.lower()}-0.jsonl"
    bad = [r["kind"] for r in rows if not line_valid(r)]
    assert bad == [], f"{len(bad)} invalid line(s), kinds {sorted(set(bad))}"


def test_summary_floor_is_the_floor_asked_for_and_where_the_scout_ended(real):
    floor, _, rows = real
    s = summary(rows)
    assert s["floor"] == floor
    assert s["reached"] and s["final_level"] == floor


def test_the_summary_route_reaches_that_floor(real):
    floor, _, rows = real
    s = summary(rows)
    assert s["route"] == "ok" and s["route_k"][1] == FLOOR_K[floor]


def test_evaluate_reads_the_floor_from_the_summary(real):
    floor, _, rows = real
    stripped = [{k: v for k, v in r.items() if k != "floor"} if r["kind"] == "summary" else r
                for r in rows if r["kind"] != "verdict"]
    judged = evaluate(stripped)                       # no floor: judged as B2, the pre --floor default
    if floor == "B2":
        assert judged == evaluate([r for r in rows if r["kind"] != "verdict"])
    else:
        assert STEPS[0] in judged["failed"] and STEPS[8] in judged["failed"]
