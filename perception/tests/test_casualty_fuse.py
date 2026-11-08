"""CASUALTY-FUSE (#166): wall-range thermal guesses are one provisional track that the first
triangulation takes over (same id), never a trail of stale casualties at full confidence.

Hand-made sensors/scout frames, no sim: the casualty is at CASUALTY; from the first poses the LiDAR
ray along the thermal bearing stops on a nearer surface (debris), so those thermal points are wrong
and drift as the Scout edges forward. A pose BASELINE away then crosses the bearings at the casualty.
"""

import math

import pytest

from perception.casualties import MERGE, Casualties, column_bearing

CASUALTY = (2.0, 1.0)
PEAK_COL = 7                      # thermal peak column; its bearing is column_bearing(7) off the yaw
MISS = 6.0


def frame(xy, surface=None):
    """The Scout at xy facing so the thermal peak points at CASUALTY; LiDAR along that bearing returns
    `surface` metres (a nearer surface) or the true distance."""
    bearing = math.atan2(CASUALTY[1] - xy[1], CASUALTY[0] - xy[0])
    yaw = bearing - column_bearing(PEAK_COL)
    grid = [[0.1] * 16 for _ in range(12)]
    for col, v in ((PEAK_COL - 1, 0.7), (PEAK_COL, 0.9), (PEAK_COL + 1, 0.7)):
        grid[6][col] = v
    rng = surface if surface is not None else math.dist(xy, CASUALTY)
    lidar = [MISS] * 360
    k = round((bearing % (2 * math.pi)) / (2 * math.pi) * 360)
    for d in (-2, -1, 0, 1, 2):
        lidar[(k + d) % 360] = rng
    return {"pose": {"pos": [xy[0], xy[1], 0.075], "yaw": yaw}, "lidar": lidar, "thermal": grid,
            "acoustic": None}


# Close together (< 1 m apart, so no ray pair is intersected) with foreground returns: the median
# thermal point starts 0.3 m out from the first pose and drifts > MERGE once the 1.2 m returns dominate.
NEAR = [frame((0.0, 0.0), 0.3)] * 3 + [frame((0.4, 0.0), 1.2)] * 6
FAR = [frame((0.5, 1.8))] * 3      # 1.87 m from the first pose; bearings cross at about 54 degrees


def test_foreground_points_drift_but_stay_one_provisional_track():
    c = Casualties(vision_on=False)
    first = None
    for f in NEAR:
        c.on_sensors(f)
        out = c.message()
        assert len(out) == 1, out                       # a drifting guess is never a second casualty
        first = first or out[0]["pos"][:2]
    assert not c.crossings
    assert math.dist(first, c.message()[0]["pos"][:2]) > MERGE      # it really did drift that far
    assert c.found[0]["supported"] is False


def test_first_crossing_moves_the_same_track_to_the_casualty():
    c = Casualties(vision_on=False)
    for f in NEAR + FAR:
        c.on_sensors(f)
    out = c.message()
    assert c.crossings
    assert [e["id"] for e in out] == ["c1"], out        # no stale c1/c2 left behind
    assert math.dist(out[0]["pos"][:2], CASUALTY) < 0.1, out[0]["pos"]
    assert c.found[0]["supported"] is True


def test_clues_gathered_while_provisional_are_kept():
    c = Casualties(vision_on=False)
    for f in NEAR:
        c.on_sensors(f)
    c.found[0]["vision"] = 1.0                           # e.g. the offline camera agreed meanwhile
    before = c.message()[0]["confidence"]
    for f in FAR:
        c.on_sensors(f)
    assert c.message()[0]["confidence"] == pytest.approx(before)


def test_triangulated_from_the_start_is_supported_and_single():
    c = Casualties(vision_on=False)
    for f in [frame((0.0, 0.0))] * 2 + FAR:
        c.on_sensors(f)
    out = c.message()
    assert len(out) == 1 and math.dist(out[0]["pos"][:2], CASUALTY) < 0.1
    assert c.found[0]["supported"] is True
