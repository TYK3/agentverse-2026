"""SUMMARY-HAS-TICKS: a run log's summary says how many 0.1 s sim ticks the run took, and the log agrees.

tools/run_b2.py ticks the sim at DT = 0.1 s and ends with "summary" (t = sim seconds at the end) then
"verdict". No record states the tick count, and coord/run_log_schema.json's summary forbids extra fields, so
today the count is only implied by summary.t. This checks what holds now:

  - exactly one summary, then the verdict, both at the same t;
  - summary.t is on the tick grid (a whole number of 0.1 s ticks) and so is every record's t;
  - no record is later than the summary: the run ends where the summary says;
  - the implied tick count covers every distinct tick seen in the log;
  - if the summary does carry "ticks", it is a whole number equal to t / DT.

The explicit field is a strict xfail on the real log: it flips once run_b2.py writes "ticks" in its summary
and the schema allows it (a tools + coord change, not this test's). The checked-in real B2 log runs in CI and
broken copies of it fail; RUN_B2_REAL=1 also checks fresh --floor B1/B2/B3 seed 0 runs (~3 min).
"""

import copy
import json
import os
import pathlib

import pytest

from tools import run_b2

ROOT = pathlib.Path(__file__).resolve().parents[2]
REAL_B2 = ROOT / "console" / "tests" / "fixtures" / "b2-seed0.jsonl"
DT = 0.1
EPS = 1e-6


def load(path):
    return [json.loads(line) for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines() if line]


def on_grid(t):
    return abs(t / DT - round(t / DT)) < EPS


def tick_problems(records):
    """Every way the summary's tick count is missing or disagrees with the log; [] means none."""
    summaries = [r for r in records if r["kind"] == "summary"]
    if len(summaries) != 1:
        return [f"{len(summaries)} summary records, want 1"]
    s = summaries[0]
    bad = []
    verdicts = [r for r in records if r["kind"] == "verdict"]
    if len(verdicts) != 1 or verdicts[0]["t"] != s["t"]:
        bad.append(f"verdict t {[v['t'] for v in verdicts]} is not the summary's {s['t']}")
    if not on_grid(s["t"]):
        bad.append(f"summary t={s['t']} is not a whole number of {DT} s ticks")
    off = [r["t"] for r in records if not on_grid(r["t"])]
    if off:
        bad.append(f"records off the tick grid at t={off[:3]}")
    late = [(r["kind"], r["t"]) for r in records if r["t"] > s["t"] + EPS]
    if late:
        bad.append(f"records after the summary's t={s['t']}: {late[:3]}")
    ticks = round(s["t"] / DT)
    seen = {round(r["t"] / DT) for r in records}
    if seen and max(seen) > ticks:
        bad.append(f"the log reaches tick {max(seen)}, the summary only {ticks}")
    if "ticks" in s:
        if not isinstance(s["ticks"], int) or isinstance(s["ticks"], bool):
            bad.append(f"summary ticks {s['ticks']!r} is not a whole number")
        elif s["ticks"] != ticks:
            bad.append(f"summary ticks {s['ticks']} but t={s['t']} is {ticks} ticks")
    return bad


@pytest.fixture(scope="module")
def real_b2():
    return load(REAL_B2)


def test_the_real_b2_summary_implies_a_tick_count_the_log_agrees_with(real_b2):
    s = next(r for r in real_b2 if r["kind"] == "summary")
    assert round(s["t"] / DT) == 1793
    assert tick_problems(real_b2) == []


def _summary(out):
    return next(r for r in out if r["kind"] == "summary")


def _off_grid(out):
    _summary(out)["t"] = 179.35


def _record_after_end(out):
    late = copy.deepcopy(next(r for r in out if r["kind"] == "pose"))
    late["t"] = 181.0
    out.insert(out.index(_summary(out)), late)


def _verdict_elsewhere(out):
    next(r for r in out if r["kind"] == "verdict")["t"] = 170.0


def _two_summaries(out):
    out.insert(out.index(_summary(out)), copy.deepcopy(_summary(out)))


def _wrong_ticks(out):
    _summary(out)["ticks"] = 1000


def _ticks_not_whole(out):
    _summary(out)["ticks"] = 1793.0


BROKEN = {
    "summary off the tick grid": (_off_grid, "not a whole number of"),
    "a record after the summary": (_record_after_end, "after the summary"),
    "verdict at another time": (_verdict_elsewhere, "is not the summary's"),
    "two summaries": (_two_summaries, "2 summary records"),
    "ticks that disagree with t": (_wrong_ticks, "summary ticks 1000 but"),
    "ticks not a whole number": (_ticks_not_whole, "is not a whole number"),
}


@pytest.mark.parametrize("name", BROKEN)
def test_a_broken_tick_count_is_caught(real_b2, name):
    change, expect = BROKEN[name]
    out = copy.deepcopy(real_b2)
    change(out)
    bad = tick_problems(out)
    assert any(expect in line for line in bad), f"{name}: not caught; found {bad}"


def test_a_correct_explicit_tick_count_passes(real_b2):
    out = copy.deepcopy(real_b2)
    _summary(out)["ticks"] = 1793
    assert tick_problems(out) == []


@pytest.mark.xfail(strict=True, reason="run_b2.py writes no ticks in its summary, and "
                                       "coord/run_log_schema.json's summary forbids extra fields")
def test_the_real_b2_summary_states_its_ticks(real_b2):
    assert "ticks" in _summary(real_b2)


@pytest.mark.skipif(os.environ.get("RUN_B2_REAL") != "1", reason="real MuJoCo runs: set RUN_B2_REAL=1 (~3 min)")
@pytest.mark.parametrize("floor", ["B1", "B2", "B3"])
def test_fresh_real_runs(tmp_path, floor):
    pytest.importorskip("mujoco")
    _, path = run_b2.run(seed=0, out_dir=tmp_path, floor=floor)
    assert tick_problems(load(path)) == []
