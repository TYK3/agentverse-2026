"""L4 multi-level map (perception/levels.py) on hand-made sensors/scout frames: no sim needed."""

import math

from perception.levels import RIDE, GridLevels, k_of

MISS = 6.0


def frame(x, y, floor, lidar=None, state="idle", target=None):
    return {"pose": {"pos": [x, y, floor + RIDE], "yaw": 0.0}, "lidar": lidar or [MISS] * 360,
            "motion": {"state": state, "target": target}}


def wall_at(dist, towards_deg):
    """LiDAR with one wall: every ray within 10 degrees of `towards_deg` returns `dist`."""
    return [dist if abs((a - towards_deg + 180) % 360 - 180) <= 10 else MISS for a in range(360)]


def test_k_is_floor_height():
    assert (k_of(0.0), k_of(0.6), k_of(-0.6)) == (0, 12, -12)
    g = GridLevels()
    g.add_sensors(frame(1.0, 1.0, 0.6))
    assert g.levels() == [12]
    assert g.cells[(20, 20, 12)] == {"state": "seen", "occupied": False, "source": "trail"}


def test_same_column_holds_two_levels():
    g = GridLevels()
    g.add_sensors(frame(1.0, 1.0, 0.6))
    g.add_sensors(frame(1.0, 1.0, -0.6))
    ks = sorted(k for (i, j, k) in g.cells if (i, j) == (20, 20))
    assert ks == [-12, 12]


def test_lidar_on_flat_floor_maps_free_space_and_hits_at_its_level():
    g = GridLevels()
    g.add_sensors(frame(1.0, 1.0, 0.0, lidar=wall_at(1.0, 0)))
    assert g.cells[(40, 20, 0)]["occupied"] is True               # the wall 1 m east, at k = 0
    assert g.cells[(30, 20, 0)]["occupied"] is False              # free space before it


def test_trail_clears_lidar_floor_that_was_air():
    g = GridLevels()
    g.add_sensors(frame(1.0, 1.0, 0.6))                           # on L1: rays east mark k=12 free
    assert (24, 20, 12) in g.cells
    g.add_sensors(frame(1.225, 1.0, 0.55))                        # the Scout stands lower there: a ramp
    assert (24, 20, 12) not in g.cells
    assert g.cells[(24, 20, 11)]["source"] == "trail"
    assert g.message(0)["cells"]                                   # the delta reports the change


def test_on_a_ramp_only_rays_across_the_slope_map():
    g = GridLevels()
    for n in range(8):                                            # drive down a 30 % slope along +x
        g.add_sensors(frame(1.0 + 0.05 * n, 1.0, 0.6 - 0.015 * n))
    x, y, f = 1.35, 1.0, 0.6 - 0.015 * 7
    up_hit = [0.25 if 170 <= a <= 190 else (0.5 if 80 <= a <= 100 else MISS) for a in range(360)]
    before = {c for c, v in g.cells.items() if v["occupied"]}
    g.add_sensors(frame(x, y, f, lidar=up_hit))
    k = k_of(f)
    new_hits = {c for c, v in g.cells.items() if v["occupied"]} - before
    assert (math.floor((x - 0.25) / 0.05), 20, k) not in new_hits    # the ramp surface uphill: ignored
    assert (27, math.floor((y + 0.5) / 0.05), k) in new_hits          # the side wall across the slope


def test_a_refused_step_marks_the_cells_ahead():
    g = GridLevels()
    g.add_sensors(frame(1.0, 1.0, 0.0, state="blocked", target=[1.5, 1.0]))
    assert g.cells[(22, 20, 0)]["occupied"] is True
    g2 = GridLevels()
    g2.add_sensors(frame(1.0, 1.0, 0.0, state="blocked", target=[1.0, 1.0]))   # wrong level only
    assert not any(v["occupied"] for v in g2.cells.values())
