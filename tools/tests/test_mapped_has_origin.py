"""MAPPED-HAS-ORIGIN: the slab gets into the map from a named, measured origin, never from sim truth.

Real runs of tools/run_b2.py (seed 0) on B2 and B3: a slab lands on the Scout's route, and the runner logs
one "mapped" record when the Scout's own map (perception.levels.GridLevels) first holds occupied cells
on the slab. Each map cell carries the measurement that put it there: "lidar" (a LiDAR return), "refused"
(the sim refused a step into it) or "trail" (the Scout stood there). From each run's jsonl:
  - there is exactly one mapped record, after the shift, with at least one cell;
  - it names its origin: a non-empty list of sources, each one of the measured kinds;
  - the origin is a measurement of something in the way: lidar or refused, never trail (the Scout never
    stood on the slab), and always including lidar (the Scout saw it, not only bumped into it).
"""

import json

import pytest

from tools.run_b2 import run

pytest.importorskip("mujoco")

MEASURED = {"lidar", "refused", "trail"}      # GridLevels' cell sources (perception/levels.py)


@pytest.fixture(scope="module", params=["B2", "B3"])
def rows(request, tmp_path_factory):
    _, path = run(seed=0, out_dir=tmp_path_factory.mktemp(request.param.lower()), floor=request.param)
    return request.param, [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_one_mapped_record_after_the_shift(rows):
    floor, log = rows
    shift = next(r for r in log if r["kind"] == "shift")
    mapped = [r for r in log if r["kind"] == "mapped"]
    assert len(mapped) == 1, f"{floor}: {len(mapped)} mapped records"
    assert mapped[0]["t"] >= shift["t"] and mapped[0]["cells"] > 0


def test_the_mapped_record_names_a_measured_origin(rows):
    floor, log = rows
    m = next(r for r in log if r["kind"] == "mapped")
    assert m["sources"], f"{floor}: mapped cells with no origin"
    assert set(m["sources"]) <= MEASURED, f"{floor}: unknown origin {m['sources']}"


def test_the_origin_is_seeing_or_bumping_into_the_slab_not_standing_on_it(rows):
    floor, log = rows
    sources = set(next(r for r in log if r["kind"] == "mapped")["sources"])
    assert "trail" not in sources, f"{floor}: the Scout stood on the slab"
    assert "lidar" in sources, f"{floor}: the slab was only bumped into, never seen"
