"""SLAB-STOP: a real B2 slab shift makes the Scout stop and reroute."""

import json

import pytest

from tools.run_b2 import STOP_WINDOW, run


def test_real_slab_shift_stops_and_reroutes_around_measured_block(tmp_path):
    pytest.importorskip("mujoco")

    verdict, path = run(seed=0, out_dir=tmp_path, floor="B2")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    shift = next(r for r in records if r["kind"] == "shift")
    core = {tuple(cell) for cell in shift["core"]}

    # The slab really interrupts the route the Scout was following.
    old_route = next(r for r in reversed(records[: records.index(shift)]) if r["kind"] == "plan" and r["cells"])
    assert old_route["t"] == shift["t"]
    assert core & {tuple(cell[:2]) for cell in old_route["cells"]}

    after = [r for r in records if r["t"] >= shift["t"]]
    measured = next(r for r in after if r["kind"] == "mapped")
    assert measured["cells"] > 0 and measured["sources"]
    assert set(measured["sources"]) <= {"lidar", "refused"}

    fresh_routes = [r for r in after if r["kind"] == "plan" and r["t"] > shift["t"] and r["cells"]]
    assert fresh_routes and measured["t"] <= fresh_routes[0]["t"]
    assert all(not core.intersection(tuple(cell[:2]) for cell in r["cells"]) for r in fresh_routes)

    stops = [r for r in after if r["kind"] == "pose" and r["state"] in {"blocked", "arrived", "idle"}
             and r["t"] <= shift["t"] + STOP_WINDOW]
    assert stops, "Scout never stopped within the slab shift window"
    assert all(tuple(r["cell"][:2]) not in core for r in after if r["kind"] == "pose")
    assert verdict["failed"] == [], verdict["steps"]
