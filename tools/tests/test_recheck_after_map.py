"""RECHECK-AFTER-MAP: after a slab shift, the Scout's recheck route is planned only once the slab is in its map.

A recheck that runs before the Scout has measured the slab plans on a stale map: it can only avoid the slab
by sim truth or by luck. In a real tools/run_b2.py log, for every shift this checks, in log order (records are
written in the order they happen, and the mapped record and the recheck can share one 0.1 s tick):

  - a "mapped" record follows the shift, before any re-plan: no plan between the shift and the mapped record;
  - the recheck (the first plan after the mapped record) follows it in the log, has a route, and that route
    misses the slab's core;
  - the recheck starts where the Scout is: its first cell is within reach of the Scout's cell at the shift
    (driving speed x the time between them, plus one cell).

tools/tests/test_recheck_log.py (RECHECK-LOG) checks the mapped record's sources and timing and that every
later route misses the slab; it matches the recheck to the map by time only, so a plan written before the
mapped record in the same tick passes there. This file checks the order.

The checked-in real B2 seed-0 log runs in CI; broken copies of it must fail. RUN_B2_REAL=1 also checks fresh
tools/run_b2.py --floor B2 and B3 seed 0 runs in MuJoCo (about 2 min).
"""

import copy
import json
import math
import os
import pathlib

import pytest

from tools import run_b2

ROOT = pathlib.Path(__file__).resolve().parents[2]
REAL_B2 = ROOT / "console" / "tests" / "fixtures" / "b2-seed0.jsonl"
RES = run_b2.RES
SPEED = run_b2.MAX_JUMP / 0.1      # 0.35 m/s: run_b2's bound on the Scout's motion


def load(path):
    return [json.loads(line) for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines() if line]


def recheck_problems(records):
    """Every way a shift's recheck is not planned on a map that has the slab, as short strings; [] is none."""
    shifts = [i for i, r in enumerate(records) if r["kind"] == "shift"]
    if not shifts:
        return ["no shift record"]
    bad = []
    for i in shifts:
        shift = records[i]
        where = f"shift at t={shift['t']}"
        later = records[i + 1:]
        m = next((k for k, r in enumerate(later) if r["kind"] == "mapped"), None)
        if m is None:
            bad.append(f"{where}: the slab is never mapped")
            continue
        blind = [r["t"] for r in later[:m] if r["kind"] == "plan"]
        if blind:
            bad.append(f"{where}: re-planned at t={blind} before the slab was mapped")
        recheck = next((r for r in later[m + 1:] if r["kind"] == "plan"), None)
        if recheck is None:
            bad.append(f"{where}: no plan after the slab was mapped")
            continue
        if not recheck.get("cells"):
            bad.append(f"{where}: the recheck at t={recheck['t']} has no route ({recheck.get('status')})")
            continue
        core = {tuple(c) for c in shift["core"]}
        through = [c for c in recheck["cells"] if tuple(c[:2]) in core]
        if through:
            bad.append(f"{where}: the recheck at t={recheck['t']} goes through the slab at {through[0]}")
        scout = shift["scout"]
        here = (math.floor(scout[0] / RES), math.floor(scout[1] / RES))
        start = tuple(recheck["cells"][0][:2])
        reach = math.ceil(SPEED * max(0.0, recheck["t"] - shift["t"]) / RES) + 1
        off = max(abs(start[0] - here[0]), abs(start[1] - here[1]))
        if off > reach:
            bad.append(f"{where}: the recheck starts at {list(start)}, {off} cells from the Scout's {list(here)}")
    return bad


@pytest.fixture(scope="module")
def real_b2():
    return load(REAL_B2)


def test_the_real_b2_recheck_follows_the_mapped_slab(real_b2):
    assert recheck_problems(real_b2) == []


def _index(out, kind, after=None):
    start = 0 if after is None else after + 1
    return next(i for i in range(start, len(out)) if out[i]["kind"] == kind)


def _plan_before_mapping(out):
    s = _index(out, "shift")
    blind = copy.deepcopy(out[_index(out, "plan", s)])
    blind["t"] = out[s]["t"]
    out.insert(s + 1, blind)


def _recheck_written_before_map(out):
    # Same tick, but the plan is written before the mapped record: planned on the old map.
    m = _index(out, "mapped", _index(out, "shift"))
    p = _index(out, "plan", m)
    out[m], out[p] = out[p], out[m]


def _never_mapped(out):
    out.remove(out[_index(out, "mapped", _index(out, "shift"))])


def _recheck_through_slab(out):
    s = _index(out, "shift")
    p = _index(out, "plan", _index(out, "mapped", s))
    out[p]["cells"].insert(1, [*out[s]["core"][0], out[p]["cells"][0][2]])


def _recheck_from_elsewhere(out):
    s = _index(out, "shift")
    p = _index(out, "plan", _index(out, "mapped", s))
    out[p]["cells"][0] = [out[p]["cells"][0][0] + 10, out[p]["cells"][0][1], out[p]["cells"][0][2]]


def _recheck_without_route(out):
    s = _index(out, "shift")
    p = _index(out, "plan", _index(out, "mapped", s))
    out[p].update(status="stuck", cells=[])


BROKEN = {
    "a re-plan before the slab is mapped": (_plan_before_mapping, "before the slab was mapped"),
    "recheck written before the mapped record": (_recheck_written_before_map, "before the slab was mapped"),
    "the slab never mapped": (_never_mapped, "never mapped"),
    "recheck through the slab": (_recheck_through_slab, "goes through the slab"),
    "recheck from 10 cells away": (_recheck_from_elsewhere, "cells from the Scout"),
    "recheck with no route": (_recheck_without_route, "has no route"),
}


@pytest.mark.parametrize("name", BROKEN)
def test_a_broken_recheck_is_caught(real_b2, name):
    change, expect = BROKEN[name]
    out = copy.deepcopy(real_b2)
    change(out)
    bad = recheck_problems(out)
    assert any(expect in line for line in bad), f"{name}: not caught; found {bad}"


def test_a_log_without_a_shift_fails(real_b2):
    assert recheck_problems([r for r in real_b2 if r["kind"] != "shift"]) == ["no shift record"]


@pytest.mark.skipif(os.environ.get("RUN_B2_REAL") != "1", reason="real MuJoCo runs: set RUN_B2_REAL=1 (~2 min)")
@pytest.mark.parametrize("floor", ["B2", "B3"])
def test_fresh_real_runs(tmp_path, floor):
    pytest.importorskip("mujoco")
    _, path = run_b2.run(seed=0, out_dir=tmp_path, floor=floor)
    assert recheck_problems(load(path)) == []
