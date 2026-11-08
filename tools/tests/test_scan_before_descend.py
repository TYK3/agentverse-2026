"""SCAN-BEFORE-DESCEND: each real chained descent follows a recent source-floor scan.

Definition: before leaving the source floor's 2 cm level band, a real LiDAR
scan processed by GridLevels must occur on that floor, after its logged arrival,
and within 0.3 sim seconds of departure (the runner's three-tick scan cadence).
The runner logs levels/poses, not scan beats: passive observers retain actual
scan and departure evidence without modifying the run or fabricating log lines.
"""

import copy
import json
import math

import pytest

from perception.levels import GridLevels
from sim.levels import LevelWorld
from tools import run_levels

FLOORS = [("L1", 0.6), ("ground", 0.0), ("B1", -0.6), ("B2", -1.2), ("B3", -1.8)]
RIDE = 0.075
LEVEL_BAND = 0.0205  # level classification plus logged sensor-position rounding
MAX_SCAN_AGE = 0.3


@pytest.fixture(scope="module")
def recording(tmp_path_factory):
    scans, ticks = [], []
    add_sensors, tick = GridLevels.add_sensors, LevelWorld.tick

    def observe_scan(grid, data):
        result = add_sensors(grid, data)
        z = data["pose"]["pos"][2]
        k = round((z - RIDE) / 0.05)
        mapped = sum(c[2] == k and r["state"] == "seen" and r["source"] == "lidar"
                     for c, r in grid.cells.items())
        scans.append({"t": data["t"], "z": z, "mapped": mapped,
                      "returns": sum(math.isfinite(r) and 0 < r < 6 for r in data["lidar"])})
        return result

    def observe_tick(world, dt=0.1):
        before = float(world.pos[2])
        result = tick(world, dt)
        ticks.append({"t": round(world.t, 2), "before_z": before, "z": float(world.pos[2])})
        return result

    path = tmp_path_factory.mktemp("scan-before-descend") / "levels-0.jsonl"
    with pytest.MonkeyPatch.context() as observe:
        observe.setattr(GridLevels, "add_sensors", observe_scan)
        observe.setattr(LevelWorld, "tick", observe_tick)
        assert run_levels.main(["--seed", "0", "--out", str(path)]) == 0
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return records, scans, ticks


def assert_scan_before_descend(records, scans, ticks):
    levels = [r for r in records if r["kind"] == "level"]
    assert [r["level"] for r in levels] == [name for name, _ in FLOORS]
    departures = []
    for index, (source, height) in enumerate(FLOORS[:-1]):
        arrived, lower = levels[index]["t"], levels[index + 1]["t"]
        departures_here = [tick for tick in ticks if arrived < tick["t"] < lower
                           and abs(tick["before_z"] - RIDE - height) <= LEVEL_BAND
                           and tick["z"] - RIDE < height - LEVEL_BAND]
        assert departures_here, f"a real departure from {source} to the next floor is required"
        departed = departures_here[0]["t"]
        candidates = [s for s in scans if arrived <= s["t"] < departed
                      and abs(s["z"] - RIDE - height) <= LEVEL_BAND
                      and s["mapped"] > 0 and s["returns"] > 0]
        assert candidates, f"a real mapped LiDAR scan on {source} must precede descent"
        latest = max(candidates, key=lambda s: s["t"])
        assert departed - latest["t"] <= MAX_SCAN_AGE + 1e-6, (source, "scan too stale", latest, departed)
        departures.append((source, departed))
    assert len(departures) == 4  # L1->ground, ground->B1, B1->B2, B2->B3


def test_real_chained_run_scans_each_source_floor_before_descent(recording):
    assert_scan_before_descend(*recording)


@pytest.mark.parametrize("mutation", ["missing_scan", "late_scan", "wrong_floor", "unmapped_scan", "missing_level"])
def test_real_recording_mutations_cannot_claim_scan_before_descent(recording, mutation):
    records, scans, ticks = copy.deepcopy(recording)
    assert_scan_before_descend(records, scans, ticks)
    b1_scans = [s for s in scans if abs(s["z"] - RIDE - (-0.6)) <= LEVEL_BAND]
    assert b1_scans
    if mutation == "missing_scan":
        scans = [s for s in scans if s not in b1_scans]
    elif mutation == "late_scan":
        lower = next(r["t"] for r in records if r["kind"] == "level" and r["level"] == "B2")
        for scan in b1_scans:
            scan["t"] = lower + 0.1
    elif mutation == "wrong_floor":
        for scan in b1_scans:
            scan["z"] = RIDE
    elif mutation == "unmapped_scan":
        for scan in b1_scans:
            scan["mapped"] = 0
    else:
        records = [r for r in records if not (r["kind"] == "level" and r["level"] == "B2")]
    with pytest.raises(AssertionError):
        assert_scan_before_descend(records, scans, ticks)
