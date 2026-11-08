"""RECHECK-AFTER-STOP: after a slab shift the Scout stops first, then rechecks on a map that holds the slab.

Real runs of tools/run_b2.py (seed 0) on B2 and B3. In its loop the Scout plans only while stopped, so a
plan record is also a stop; a pose record carries the motion state. Order is the log's (records with
the same time keep the order they were written in). From each run's jsonl, after the shift:
  - the Scout stops (a pose that is not moving, or a plan) before any pose of it inside the slab;
  - the recheck is the first plan made once the slab is mapped (the "mapped" record): it comes at or
    after that stop and that mapping, so it was planned on a map that already holds the slab;
  - the recheck's path avoids the slab.
"""

import json

import pytest

from tools.run_b2 import run

pytest.importorskip("mujoco")


@pytest.fixture(scope="module", params=["B2", "B3"])
def rows(request, tmp_path_factory):
    _, path = run(seed=0, out_dir=tmp_path_factory.mktemp(request.param.lower()), floor=request.param)
    return request.param, [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def events(log):
    """(index of shift, of the first stop after it, of mapped, of the recheck plan), and the records."""
    i_shift = next(i for i, r in enumerate(log) if r["kind"] == "shift")
    i_stop = next(i for i, r in enumerate(log) if i > i_shift and (
        r["kind"] == "plan" or (r["kind"] == "pose" and r["state"] != "moving")))
    i_mapped = next(i for i, r in enumerate(log) if r["kind"] == "mapped")
    i_recheck = next(i for i, r in enumerate(log) if i > i_mapped and r["kind"] == "plan")
    return i_shift, i_stop, i_mapped, i_recheck


def test_the_scout_stops_after_the_shift_before_reaching_the_slab(rows):
    floor, log = rows
    i_shift, i_stop, _, _ = events(log)
    core = {tuple(c) for c in log[i_shift]["core"]}
    inside = next((i for i, r in enumerate(log) if i > i_shift and r["kind"] == "pose"
                   and tuple(r["cell"][:2]) in core), None)
    assert inside is None or i_stop < inside, f"{floor}: inside the slab before stopping"
    assert log[i_stop]["t"] - log[i_shift]["t"] <= 3.0


def test_the_recheck_comes_after_the_stop_and_after_the_slab_is_mapped(rows):
    floor, log = rows
    _, i_stop, i_mapped, i_recheck = events(log)
    assert i_recheck >= i_stop and i_recheck > i_mapped, f"{floor}: stop {i_stop}, mapped {i_mapped}, " \
                                                         f"recheck {i_recheck}"
    assert log[i_recheck]["t"] >= log[i_mapped]["t"]


def test_the_recheck_avoids_the_slab(rows):
    floor, log = rows
    i_shift, _, _, i_recheck = events(log)
    core = {tuple(c) for c in log[i_shift]["core"]}
    assert not core & {tuple(c[:2]) for c in log[i_recheck]["cells"]}, f"{floor}: recheck plan crosses the slab"
