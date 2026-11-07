"""T08 checks on a synthetic square room: walls seen after one sweep, nothing behind them, no going back."""

import asyncio
import math

import perception
from perception import replay
from perception.grid import Grid, cell_of

HALF = 1.02           # room walls at x, y = +-1.02 m (off the 0.05 m grid lines)
Z = 0.075             # LiDAR height, layer k = 1


def sweep(pos, n=360):
    """Ranges from `pos` to the walls of the room, ray k at 2*pi*k/n like sim's LiDAR."""
    out = []
    for k in range(n):
        a = 2 * math.pi * k / n
        dx, dy = math.cos(a), math.sin(a)
        tx = (math.copysign(HALF, dx) - pos[0]) / dx if abs(dx) > 1e-9 else math.inf
        ty = (math.copysign(HALF, dy) - pos[1]) / dy if abs(dy) > 1e-9 else math.inf
        out.append(min(tx, ty))
    return out


def wall_cells():
    """Every cell the room's wall surface passes through at the LiDAR height."""
    lo, hi = cell_of((-HALF, -HALF, Z)), cell_of((HALF, HALF, Z))
    k = lo[2]
    out = set()
    for i in range(lo[0], hi[0] + 1):
        out |= {(i, lo[1], k), (i, hi[1], k)}
    for j in range(lo[1], hi[1] + 1):
        out |= {(lo[0], j, k), (hi[0], j, k)}
    return out


def test_walls_seen_after_one_sweep():
    g = Grid()
    g.add_scan((0.0, 0.0, Z), sweep((0.0, 0.0)))
    for c in wall_cells():
        assert g.state(c) == "seen" and g.cells[c]["occupied"], c
    assert g.state(cell_of((0.0, 0.0, Z))) == "seen" and not g.cells[cell_of((0.0, 0.0, Z))]["occupied"]


def test_cell_behind_wall_stays_unknown():
    g = Grid()
    g.add_scan((0.0, 0.0, Z), sweep((0.0, 0.0)))
    assert g.state(cell_of((HALF + 0.2, 0.0, Z))) == "unknown"
    assert g.state(cell_of((0.0, 0.0, Z + 0.1))) == "unknown"     # layers the LiDAR never swept


def test_rescan_never_unsees():
    g = Grid()
    g.add_scan((0.0, 0.0, Z), sweep((0.0, 0.0)))
    before = {c for c, v in g.cells.items() if v["state"] == "seen"}
    occupied = {c for c, v in g.cells.items() if v["occupied"]}
    for pos in [(0.6, 0.4), (-0.7, -0.5), (0.0, 0.9)]:
        g.add_scan((*pos, Z), sweep(pos))
        assert all(g.state(c) == "seen" for c in before)
        assert all(g.cells[c]["occupied"] for c in occupied)      # a grazing ray does not clear a wall


def test_miss_marks_nothing():
    g = Grid()
    g.add_scan((0.0, 0.0, Z), [6.0] * 360)
    assert g.cells == {}


def test_inference_fills_hidden_interior_only():
    g = Grid()
    hidden = (5, 5, 1)
    walls = [(6, 5, 1), (4, 5, 1), (5, 6, 1)]                    # three side neighbours, same layer only
    for c in walls:
        g.hit(c)
    g.infer(walls)
    assert g.cells[hidden] == {"state": "inferred", "occupied": True, "hits": 0}
    assert g.state((5, 5, 0)) == g.state((5, 5, 2)) == "unknown"  # never infer across layers

    g = Grid()
    for c in walls[:2]:
        g.hit(c)
    g.infer(walls[:2])
    assert g.state(hidden) == "unknown"                           # two walls is a gap, not an interior

    g = Grid()
    for c in walls:
        g.free(c)
    g.infer(walls)
    assert g.state(hidden) == "unknown"                           # free space is never inferred


def test_map_cells_messages():
    g = Grid()
    g.add_scan((0.0, 0.0, Z), sweep((0.0, 0.0)))
    first = g.delta(0.5)
    assert set(first) == {"t", "res", "cells"} and first["res"] == 0.05
    assert len(first["cells"]) == len(g.cells)
    assert set(first["cells"][0]) == {"cell", "state", "occupied"}
    assert g.delta(1.0)["cells"] == []                            # nothing changed since
    g.add_scan((0.6, 0.4, Z), sweep((0.6, 0.4)))
    assert len(g.snapshot(5.0)["cells"]) == len(g.cells)
    assert g.delta(5.5)["cells"] == []                            # the snapshot counts as the last message


def test_start_publishes_changes_then_snapshot(monkeypatch):
    class FakeBus:
        def __init__(self):
            self.subs, self.sent = {}, []

        def subscribe(self, topic, fn):
            self.subs[topic] = fn

        async def publish(self, topic, data):
            self.sent.append((topic, data))

    async def run():
        monkeypatch.setattr(perception, "PERIOD", 0.01)
        bus = FakeBus()
        grid = await perception.start(bus)
        bus.subs["sensors/scout"]({"pose": {"pos": [0.0, 0.0, Z], "yaw": 0.0}, "lidar": sweep((0.0, 0.0))})
        await asyncio.sleep(0.15)
        return bus, grid

    bus, grid = asyncio.run(run())
    assert {t for t, _ in bus.sent} == {"map/cells"}
    sizes = [len(d["cells"]) for _, d in bus.sent]
    assert sizes[0] == len(grid.cells)                            # the first tick sends every change
    assert len(grid.cells) in sizes[1:]                           # tick 10 is a full snapshot


def test_standin_replay_seen_count_rises():
    assert replay.main([str(replay.STANDIN)]) == 0
