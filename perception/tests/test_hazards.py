"""Z1 checks: map/hazards from the Scout's own scans. Depth-point overhangs before a shake, the LiDAR scan
diff after it, and the backup scene scored against sim truth (which perception never reads)."""

import asyncio

import pytest

import perception
from perception.cloud import Cloud
from perception.grid import Grid
from perception.hazards import LAYERS, Hazards

K = 1


def open_floor(g, cells):
    for c in cells:
        for _ in range(3):
            g.free((*c, K))


def slab_points(x0, x1, y0, y1, z0, z1, step=0.025):
    """Points on a box surface region, like a depth camera's returns off it."""
    out = []
    x = x0
    while x < x1:
        y = y0
        while y < y1:
            out += [[x, y, z0], [x, y, z1]]
            y += step
        x += step
    return out


def leaning_slab():
    """A wall at x = 0.50-0.55 m and a slab 0.3-0.5 m up over open floor west of it."""
    g = Grid()
    open_floor(g, [(i, j) for i in range(10) for j in range(6)])
    for j in range(6):
        g.hit((10, j, K))
    cloud = Cloud()
    cloud.add(slab_points(0.30, 0.50, 0.05, 0.25, 0.30, 0.50))         # floats: overhang
    cloud.add(slab_points(0.50, 0.55, 0.00, 0.30, 0.05, 0.95))         # the wall it leans on, to the floor
    return g, cloud


def test_overhang_over_open_floor_and_its_support_are_at_risk():
    g, cloud = leaning_slab()
    risky = cloud.risks(g, 0.0)
    assert {(i, j) for i in range(6, 10) for j in range(1, 5)} <= set(risky)
    assert risky[(7, 2)].startswith("pile stability 0.00: overhang 0.30-0.50 m above open floor")
    assert "carries an overhang" in risky[(10, 2)]                    # the wall it leans on
    assert (0, 0) not in risky and (2, 2) not in risky                 # open floor far from the slab


def test_points_over_unseen_floor_or_reaching_the_floor_are_not_overhangs():
    g = Grid()
    cloud = Cloud()
    cloud.add(slab_points(0.0, 0.2, 0.0, 0.2, 0.3, 0.5))               # the LiDAR never saw the floor below
    assert cloud.risks(g, 0.0) == {}
    open_floor(g, [(i, j) for i in range(4) for j in range(4)])
    cloud.reset()
    cloud.add(slab_points(0.0, 0.2, 0.0, 0.2, 0.05, 0.5))              # a pillar standing on the floor
    assert cloud.risks(g, 0.0) == {}


def test_without_depth_points_nothing_is_predicted():
    g, _ = leaning_slab()
    h = Hazards(g)
    assert h.update(0.0) == [] and h.status((7, 2)) == "stable"


def test_prediction_stays_after_the_shake_until_rescanned():
    g, cloud = leaning_slab()
    h = Hazards(g, cloud)
    h.update(1.0)
    assert h.status((7, 2)) == "at_risk"
    h.on_change({"kind": "aftershock", "t": 2.0, "moved_blocks": ["b10"]}, 2.0)
    msg = h.update(2.0)
    cell = next(m for m in msg if m["cell"][:2] == [7, 2])
    assert cell["status"] == "at_risk" and "predicted before the aftershock at 2.0 s, not re-scanned yet" in cell["why"]
    g.free((7, 2, K))                                                  # the Scout measures that column again
    h.update(3.0)
    assert h.status((7, 2)) == "stable" and h.status((8, 2)) == "at_risk"


def test_scan_diff_debris_is_collapsed_with_a_ring_and_cleared_cells_at_risk():
    g = Grid()
    open_floor(g, [(i, 0) for i in range(20)])
    g.hit((25, 0, K))                                                  # something that will move away
    h = Hazards(g)
    h.on_change({"kind": "aftershock", "t": 5.0, "moved_blocks": ["anything"]}, 5.0)
    g.t = 6.0
    g.hit((10, 0, K))
    h.update(6.0)
    assert h.status((10, 0)) == "stable"                               # one return is not enough
    g.hit((10, 0, K))
    for _ in range(3):
        g.free((25, 0, K))                                             # rays now pass where it stood
    msg = h.update(6.0)
    assert h.status((10, 0)) == "collapsed" and h.status((13, 0)) == "at_risk" and h.status((14, 0)) == "stable"
    assert h.status((25, 0)) == "at_risk"
    why = {tuple(m["cell"][:2]): m["why"] for m in msg}
    assert why[(10, 0)] == "scan diff: debris landed here in the aftershock at 5.0 s (seen at 6.0 s)"
    assert why[(25, 0)].startswith("scan diff: what stood here moved in the aftershock at 5.0 s")
    assert h.update(6.0) is None                                      # unchanged: nothing to publish


def test_injected_block_is_found_by_the_scan_diff():
    g = Grid()
    open_floor(g, [(i, 0) for i in range(20)])
    h = Hazards(g)
    h.on_change({"kind": "block_added", "t": 2.0, "moved_blocks": ["x1"]}, 2.0)
    g.hit((5, 0, K))
    g.hit((5, 0, K))
    h.update(2.5)
    assert h.labels[(5, 0)] == ("collapsed", "scan diff: debris landed here in the injected block at 2.0 s (seen at 2.0 s)")


def test_message_shape_matches_contract():
    g, cloud = leaning_slab()
    msg = Hazards(g, cloud).update(0.0)
    assert msg and {m["cell"][2] for m in msg} == set(LAYERS)
    for m in msg:
        assert set(m) == {"cell", "status", "why", "estimate"}
        assert m["status"] in ("at_risk", "collapsed") and m["estimate"] is True
        assert len(m["cell"]) == 3 and all(isinstance(v, int) for v in m["cell"])


def test_start_ignores_block_poses_and_publishes_scan_hazards(monkeypatch):
    class FakeBus:
        def __init__(self):
            self.subs, self.sent = {}, []

        def subscribe(self, topic, fn):
            self.subs.setdefault(topic, []).append(fn)

        async def publish(self, topic, data):
            self.sent.append((topic, data))
            for fn in self.subs.get(topic, []):
                result = fn(data)
                if asyncio.iscoroutine(result):
                    await result

    monkeypatch.setattr(perception, "PERIOD", 0.01)

    async def run():
        bus = FakeBus()
        await perception.start(bus)
        assert "scene/loaded" not in bus.subs                         # block poses are sim truth
        scan = {"t": 1.0, "pose": {"pos": [0.0, 0.0, 0.075], "yaw": 0.0}, "lidar": [1.0] * 360,
                "thermal": [[0.1]], "acoustic": {"bearing": 0, "level": 0.0},
                "points": slab_points(0.3, 0.5, -0.1, 0.1, 0.3, 0.5)}
        for _ in range(3):
            await bus.publish("sensors/scout", scan)
        await asyncio.sleep(0.05)
        await bus.publish("world/change", {"kind": "aftershock", "t": 2.0, "moved_blocks": ["b1"]})
        await asyncio.sleep(0.05)
        for task in list(perception._tasks):
            task.cancel()
        return [d for t, d in bus.sent if t == "map/hazards"]

    published = asyncio.run(run())
    assert published and any(m["status"] == "at_risk" and "overhang" in m["why"] for m in published[0])
    assert all("b1" not in m["why"] for msg in published for m in msg)


# ---- the backup scene (needs mujoco) -------------------------------------------

@pytest.fixture(scope="module")
def shaken():
    """90 s of exploring with LiDAR + depth points, an aftershock that really moves b8, b10, b11, then 30 s more."""
    pytest.importorskip("mujoco")
    from perception.tests.closed_loop import Loop, footprint
    loop = Loop()
    loop.run(90)
    before = {ij for ij, (s, _) in loop.hazards.labels.items() if s == "at_risk"}
    truth_before = footprint(loop.m, loop.d, "b10") | footprint(loop.m, loop.d, "b8")
    stood = footprint(loop.m, loop.d, "b8") | footprint(loop.m, loop.d, "b11")
    step = len(loop.trail)
    loop.aftershock()
    loop.run(30)
    fell = set().union(*(footprint(loop.m, loop.d, n) for n in ("b8", "b10", "b11")))
    return loop, before, truth_before, stood, fell, step


def test_backup_prediction_from_depth_points_finds_b10_and_b8(shaken):
    from perception.score import score
    _, before, truth, _, _, _ = shaken
    s = score(before, truth, near=1)
    assert s["precision"] >= 0.9 and s["recall"] >= 0.5, s           # measured: 1.0 and 0.69


def test_backup_scan_diff_finds_what_fell_and_what_left(shaken):
    from perception.score import score
    loop, _, _, stood, fell, _ = shaken
    collapsed = {ij for ij, (s, _) in loop.hazards.labels.items() if s == "collapsed"}
    cleared = {(c[0], c[1]) for c in loop.grid.cleared}
    s_fell, s_left = score(collapsed, fell, near=1), score(cleared, stood, near=1)
    assert s_fell["precision"] >= 0.9 and s_fell["predicted"] >= 30, s_fell     # measured: 0.99, 78 cells
    assert s_left["precision"] >= 0.7 and s_left["recall"] >= 0.8, s_left     # measured: 0.82, 0.97
