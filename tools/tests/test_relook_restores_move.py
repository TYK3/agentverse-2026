"""RELOOK-RESTORES-MOVE: a real B2 stop is followed by scan, re-plan, then motion.

Definition: after the shifted slab stops the Scout, its first nonzero movement
must follow a fresh scan measuring the slab and a new logged route. This checks
the runner's observed ordering, not a Responder movement-permit implementation.
The 1 Hz log is paired with passive real-tick/scan observations to see the halt
that can fall between logged poses. All observed production methods still run.
"""

import copy
import json
import math

import pytest

from perception.levels import GridLevels
from sim.levels import LevelWorld
from tools import run_b2


def distance(event):
    return math.dist(event["before"], event["pos"])


@pytest.fixture(scope="module")
def recording(tmp_path_factory):
    events, slab = [], {}
    tick, scan, drop = LevelWorld.tick, GridLevels.add_sensors, run_b2.drop_slab

    def observe_tick(world, dt=0.1):
        before = world.pos.tolist()
        result = tick(world, dt)
        events.append({"kind": "tick", "t": round(world.t, 2), "state": world.state,
                       "before": before, "pos": world.pos.tolist()})
        return result

    def observe_scan(grid, data):
        result = scan(grid, data)
        if slab:
            hits = [c for c, r in grid.cells.items() if c[:2] in slab["core"]
                    and c[2] == slab["k"] and r["occupied"] and r["source"] == "lidar"]
            events.append({"kind": "scan", "t": round(data["t"], 2), "slab_hits": len(hits)})
        return result

    def observe_drop(world, xy, floor_z):
        drop(world, xy, floor_z)
        slab.update(core=run_b2.footprint(xy), k=round(floor_z / run_b2.RES))

    with pytest.MonkeyPatch.context() as observe:
        observe.setattr(LevelWorld, "tick", observe_tick)
        observe.setattr(GridLevels, "add_sensors", observe_scan)
        observe.setattr(run_b2, "drop_slab", observe_drop)
        _, path = run_b2.run(seed=0, floor="B2", out_dir=tmp_path_factory.mktemp("relook-b2"))
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return records, events


def assert_relook_restores_move(records, events):
    shifts = [r for r in records if r["kind"] == "shift"]
    assert len(shifts) == 1 and shifts[0]["level"] == "B2"
    shift = shifts[0]
    stops = [(i, e) for i, e in enumerate(events) if e["kind"] == "tick"
             and shift["t"] < e["t"] <= shift["t"] + run_b2.STOP_WINDOW
             and e["state"] in {"blocked", "arrived", "idle"} and distance(e) <= 1e-9]
    assert stops, "a real stationary stop after the slab shift is required"
    stop_i, stop = stops[0]
    scans = [(i, e) for i, e in enumerate(events) if i > stop_i
             and e["kind"] == "scan" and e["slab_hits"] > 0]
    assert scans, "a fresh post-stop scan must measure the slab"
    scan_i, scan = scans[0]
    moves = [(i, e) for i, e in enumerate(events) if i > stop_i and e["kind"] == "tick"
             and distance(e) > 0.001]
    assert moves, "the Scout must really resume moving, not remain halted"
    move_i, move = moves[0]
    assert stop_i < scan_i < move_i, "motion must not precede the re-look"
    assert stop["t"] <= scan["t"] < move["t"]
    assert move["state"] == "moving"
    mapped = [r for r in records if r["kind"] == "mapped" and r["t"] == scan["t"]]
    assert mapped and mapped[0]["cells"] > 0 and "lidar" in mapped[0]["sources"]
    plans = [r for r in records if r["kind"] == "plan" and r["status"] == "ok"
             and shift["t"] < r["t"] and scan["t"] <= r["t"] < move["t"] and r["cells"]]
    assert plans, "the fresh scan must be followed by a new logged route before motion"
    assert any(r["kind"] == "pose" and r["t"] >= move["t"] and r["state"] == "moving"
               for r in records), "the real run log must also show resumed movement"
    return stop_i, scan_i, move_i


def test_real_b2_relook_precedes_restored_movement(recording):
    assert_relook_restores_move(*recording)


@pytest.mark.parametrize("mutation", ["missing_scan", "premature_motion", "no_resume", "missing_plan"])
def test_real_recording_mutations_cannot_claim_relook_restored_motion(recording, mutation):
    records, events = copy.deepcopy(recording)
    stop_i, scan_i, move_i = assert_relook_restores_move(records, events)
    if mutation == "missing_scan":
        events = [e for e in events if e["kind"] != "scan"]
    elif mutation == "premature_motion":
        events.insert(scan_i, events.pop(move_i))
    elif mutation == "no_resume":
        for e in events[stop_i + 1:]:
            if e["kind"] == "tick":
                e["pos"] = e["before"].copy()
    else:
        shifted = next(r["t"] for r in records if r["kind"] == "shift")
        records = [r for r in records if not (r["kind"] == "plan" and r["t"] > shifted)]
    with pytest.raises(AssertionError):
        assert_relook_restores_move(records, events)
