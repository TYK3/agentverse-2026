"""ROUTE-AFTER-SHIFT: a real landed slab invalidates a route until a fresh scan.

Seam: inject/World physics -> world/change -> planner Loop -> real sensed map -> A*.
The unscripted shift uses block_added, not a fabricated world/change or hazard map.
"""

import asyncio
import math

from coord.hub import Bus
from perception.grid import Grid
from planner.loop import Loop
from planner.route import RoutePlanner
from sim import inject, scene
from sim.world import World


def test_fresh_scan_after_slab_shift_produces_a_new_route_avoiding_blocked_cell(tmp_path):
    # Real backup scene, with the parked spare shaped as the e2e runner's slab
    # (0.24 x 0.24 x 0.10 m), instead of its default small rubble block.
    xml = scene.BACKUP.read_text()
    old_geom = '<geom name="x1_rubble" type="box" size="0.1 0.1 0.08"'
    assert xml.count(old_geom) == 1
    xml = xml.replace(old_geom, '<geom name="x1_rubble" type="box" size="0.12 0.12 0.05"')
    path = tmp_path / "backup_with_slab.xml"
    path.write_text(xml)
    world = World(path=path, render=False, seed=0)
    for target in ([-0.5, 0.25, 0.075], [-1.0, 0.25, 0.075]):
        world.goto({"target": target, "reason": "survey room 1 before the shift"})
        for _ in range(100):
            world.tick(0.1)
            if world.state != "moving":
                break
        assert world.state == "arrived"

    async def run():
        bus = Bus()
        router = RoutePlanner(bus)
        bus.subscribe("map/cells", router.update_map)
        planner = Loop(bus, router).attach()
        proposed, verified = [], []
        bus.subscribe("route/proposed", proposed.append)
        bus.subscribe("route/verified", verified.append)

        async def physics(route):
            await bus.publish("route/verified", world.verify(route))

        bus.subscribe("route/proposed", physics)
        grid = Grid()
        grid.add_sensors(world.sensors_message(camera=False))
        await bus.publish("map/cells", grid.snapshot(world.t))
        start = [math.floor(v / 0.05) for v in world.pos[:2]] + [0]
        goal, blocked = [-6, 5, 0], [-16, 5, 0]
        result = await planner.mission(start, goal)
        assert result["status"] == "ok"
        assert len(proposed) == 1
        original = proposed[0]
        assert blocked in original["cells"]
        assert verified[0]["id"] == original["id"] and verified[0]["ok"] is True

        status, body = inject.handle(world, {"kind": "block_added", "pos": [-0.65, 0.25, 0.3]})
        assert (status, body) == (200, {"ok": True, "block": "x1"})
        changes = []
        for _ in range(12):
            changes.extend(data for topic, data in world.tick(0.1) if topic == "world/change")
        assert len(changes) == 1 and changes[0]["kind"] == "block_added"
        assert changes[0]["moved_blocks"] == ["x1"]
        await bus.publish("world/change", changes[0])
        assert planner.route is None
        assert planner.waiting_scan is not None
        assert len(proposed) == 1  # no stale-map route before the re-scan

        grid.begin_change(world.t)
        grid.add_sensors(world.sensors_message(camera=False))
        snapshot = grid.snapshot(world.t)
        observed = {tuple(c["cell"]): c for c in snapshot["cells"]}
        assert observed[tuple(blocked)]["state"] == "seen"
        assert observed[tuple(blocked)]["occupied"] is True
        await bus.publish("map/cells", snapshot)
        assert len(proposed) == 2
        replacement = proposed[-1]
        occupied = {tuple(c["cell"]) for c in snapshot["cells"] if c["occupied"]}
        assert blocked not in replacement["cells"]
        assert not occupied.intersection(map(tuple, replacement["cells"]))
        assert replacement["id"] != original["id"]
        assert replacement["cells"] != original["cells"]
        assert replacement["cells"][0] == start and replacement["cells"][-1] == goal
        assert verified[-1]["id"] == replacement["id"] and verified[-1]["ok"] is True
        assert any(msg["topic"] == "log/decision" and
                   "map re-scanned after block_added moved x1" in msg["data"]["perception"]
                   for msg in bus.history)
        await planner.cancel_request("test complete")

    asyncio.run(run())
