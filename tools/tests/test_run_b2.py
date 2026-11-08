"""e2e-b2 (tools/run_b2.py): the verdict on hand-made records, the slab scene and drop on the real sim.

The full B2 run is opt-in (RUN_B2_REAL=1): about 180 sim seconds, around a minute of wall time.
"""

import os

import pytest

from tools.run_b2 import STEPS, evaluate, footprint, point_ahead


def records(shift=True, reached=True, through=False, k_min=-24, stop=True):
    out = [{"t": 0.0, "kind": "level", "level": "L1"}, {"t": 20.0, "kind": "level", "level": "ground"},
           {"t": 80.0, "kind": "level", "level": "B1"}, {"t": 150.0, "kind": "level", "level": "B2"}]
    if shift:
        core = sorted(map(list, footprint((1.125, 0.975))))
        out += [{"t": 170.0, "kind": "shift", "xy": [1.125, 0.975], "level": "B2", "core": core,
                 "footprint": sorted(map(list, footprint((1.125, 0.975), 0.05))), "scout": [1.5, 1.0, -1.125]},
                {"t": 170.2, "kind": "mapped", "cells": 4, "sources": ["lidar"]}]
        if stop:
            out.append({"t": 170.5, "kind": "pose", "pos": [1.4, 1.0, -1.125], "state": "blocked", "level": "B2",
                        "cell": [28, 20, -24]})
        path = [[22, 19, -24], [21, 19, -24]] if through else [[28, 15, -24], [20, 15, -24]]
        out.append({"t": 171.0, "kind": "plan", "status": "ok", "why": "route", "cells": path})
        if through:
            out.append({"t": 172.0, "kind": "pose", "pos": [1.12, 0.97, -1.125], "state": "moving", "level": "B2",
                        "cell": [22, 19, -24]})
    out.append({"t": 180.0, "kind": "summary", "reached": reached, "final_pos": [0.77, 0.82, -1.125],
                "final_level": "B2" if reached else "ramp", "max_jump": 0.0313, "route": "ok",
                "route_k": [12, k_min]})
    return out


def test_a_clean_run_passes_every_step():
    v = evaluate(records())
    assert v["failed"] == [] and v["passed"] == list(STEPS)


def test_no_shift_fails_the_shift_steps_only():
    v = evaluate(records(shift=False))
    assert set(v["failed"]) == {STEPS[1], STEPS[2], STEPS[3], STEPS[4], STEPS[6]}


def test_driving_through_the_slab_fails():
    v = evaluate(records(through=True))
    assert STEPS[4] in v["failed"] and STEPS[6] in v["failed"]


def test_not_reaching_b2_or_a_short_route_fails():
    v = evaluate(records(reached=False, k_min=-13))
    assert STEPS[5] in v["failed"] and STEPS[8] in v["failed"]


def test_not_stopping_or_replanning_in_time_fails():
    recs = [r for r in records(stop=False) if r["kind"] != "plan"]
    recs.insert(-1, {"t": 175.0, "kind": "plan", "status": "ok", "why": "route", "cells": [[28, 15, -24]]})
    assert STEPS[2] in evaluate(recs)["failed"]


def test_point_ahead_needs_room_left():
    cells = [[i, 0, -24] for i in range(30)]                 # 1.5 m straight route
    xy = point_ahead(cells, (0.025, 0.025), ahead=0.3)
    assert xy == pytest.approx((6.5 * 0.05, 0.025))
    assert point_ahead(cells[:10], (0.025, 0.025)) is None    # 0.45 m left: under MIN_LEFT


def test_footprint_covers_the_slab():
    cells = footprint((1.0, 1.0))
    assert (20, 20) in cells and (17, 17) in cells and (22, 22) in cells
    assert len(footprint((1.0, 1.0), margin=0.05)) > len(cells)


def test_slab_scene_loads_and_the_slab_rests_on_b2(tmp_path):
    pytest.importorskip("mujoco")
    from sim.levels import LevelWorld
    from tools.run_b2 import SLAB_HALF, drop_slab, scene_with_slab

    w = LevelWorld(path=scene_with_slab(tmp_path), render=False)
    assert w.level() == "L1"
    b = w.m.body("x1").id
    drop_slab(w, (1.1, 0.95), -1.2)
    for _ in range(10):
        w.tick(0.1)
    z = float(w.d.xpos[b][2])
    assert z == pytest.approx(-1.2 + SLAB_HALF[2], abs=0.01)    # on the B2 floor, not fallen through


@pytest.mark.skipif(os.environ.get("RUN_B2_REAL") != "1", reason="full B2 run: set RUN_B2_REAL=1")
def test_real_b2_run_passes(tmp_path):
    from tools.run_b2 import run

    verdict, path = run(seed=0, out_dir=tmp_path)
    assert path.exists()
    assert verdict["failed"] == [], verdict["steps"]
