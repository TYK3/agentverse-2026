"""T06 checks: the Responder follows routes, never drives through a block, carries and places supplies,
clears only light debris, waits for an approved gate on risky routes and freezes on world/change."""

import asyncio
import itertools

import mujoco
import numpy as np
import pytest

from sim import demo_responder, scene
from sim import responder as R
from sim.world import World


@pytest.fixture
def world():
    w = World(render=False)
    w._set_pose((-1.2, -1.7), 0.0)      # Scout parked out of the way
    return w


@pytest.fixture
def resp(world):
    return R.Responder(world.m, world.d, clock=lambda: world.t)


def drive(world, r, seconds=120):
    for _ in range(int(seconds / 0.1)):
        r.step(0.1)
        world.tick(0.1)
        if r.state != "moving":
            break


def route(r, rid, points):
    r.on_route({"id": rid, "robot": "responder", "cells": R.cells_along(points), "goal": "test", "model": "local-astar"})


def pos_of(world, name):
    return world.d.xpos[world.m.body(name).id].copy()


class Overlap:
    """Checks the Responder chassis against every block with MuJoCo's own collision detection.

    A second copy of the model gives the chassis a collision type (only in the copy), so mj_forward
    lists any chassis-block contact with penetration; the real run is not affected.
    """

    def __init__(self, path=scene.BACKUP):
        self.m = mujoco.MjModel.from_xml_path(str(path))
        self.d = mujoco.MjData(self.m)
        chassis = self.m.geom("responder_chassis").id
        self.m.geom_contype[chassis], self.m.geom_conaffinity[chassis] = 2, 2
        for i in scene.block_ids(self.m):
            g = self.m.body_geomadr[i]
            self.m.geom_conaffinity[g] |= 2
        self.chassis = chassis
        self.blocks = {int(self.m.body_geomadr[i]) for i in scene.block_ids(self.m)}

    def worst(self, world):
        self.d.qpos[:] = world.d.qpos
        self.d.mocap_pos[:] = world.d.mocap_pos
        self.d.mocap_quat[:] = world.d.mocap_quat
        mujoco.mj_forward(self.m, self.d)
        worst = 0.0
        for c in self.d.contact[: self.d.ncon]:
            pair = {int(c.geom1), int(c.geom2)}
            if self.chassis in pair and pair & self.blocks:
                worst = min(worst, float(c.dist))
        return worst


def test_scene_has_responder_and_loaded_supplies():
    m, d = scene.load()
    assert m.body_mocapid[m.body("responder").id] >= 0, "responder must be a mocap body"
    chassis = m.geom("responder_chassis").id
    assert m.geom_contype[chassis] == 0 and m.geom_conaffinity[chassis] == 0
    for item in R.SUPPLIES:
        assert d.eq_active[m.equality("carry_" + item).id], f"{item} should start on the deck"
    for block in ("b11", "b13"):
        assert m.body_mass[m.body(block).id] < R.LIGHT_KG
        assert not d.eq_active[m.equality("grip_" + block).id]


def test_supplies_ride_steady_for_5_seconds(world):
    r = R.Responder(world.m, world.d)
    rel = {n: pos_of(world, n) - r.pos for n in R.SUPPLIES}
    for _ in range(50):
        world.tick(0.1)
    for n in R.SUPPLIES:
        assert np.linalg.norm(pos_of(world, n) - r.pos - rel[n]) < 0.01, n


def test_scripted_demo_delivers_water_and_clears_b11():
    world, r = demo_responder.run()
    outcomes = [e["outcome"] for e in r.log]
    assert "refused" not in outcomes and "blocked" not in outcomes, r.log
    assert outcomes.count("done") >= 5
    water, casualty = pos_of(world, "water"), pos_of(world, "casualty_c1")
    assert np.linalg.norm(water[:2] - casualty[:2]) < 0.4, "water should be next to c1"
    assert water[2] < 0.1, "water should be on the floor"
    b11 = pos_of(world, "b11")
    assert not (1.15 < b11[0] < 1.35 and 0.3 < b11[1] < 0.9), "b11 should be out of the room 2/3 gap"
    assert r.status()["carrying"] == ["first_aid_kit", "radio", "bandage", "splint", "thermal_blanket"]


def test_never_overlaps_a_block_during_the_demo():
    check, worst = Overlap(), [0.0]

    def on_step(world, _r):
        worst[0] = min(worst[0], check.worst(world))

    demo_responder.run(on_step=on_step)
    assert worst[0] > -0.005, f"chassis went {-worst[0]:.3f} m into a block"


def test_refuses_to_drive_through_a_wall(world, resp):
    # Into room 1, then east straight at interior wall b6 (x = 0)
    route(resp, "rw", [(-0.48, -1.77), (-0.48, -0.6), (0.6, -0.6)])
    resp.on_action({"action": "move", "route": "rw", "item": "water"})
    drive(world, resp)
    assert resp.state == "blocked"
    assert resp.log[-1]["outcome"] == "blocked"
    front = resp.pos[0] + R.HALF_LEN
    # It stops before the wall face (x = -0.05), at most GAP plus one step short of it.
    assert -0.05 - R.GAP - R.SPEED * 0.1 - 0.001 < front < -0.05, f"front at x={front:.3f}, wall face at -0.05"
    x = resp.pos[0]
    for _ in range(20):
        resp.step(0.1)
        world.tick(0.1)
    assert resp.pos[0] == x, "it stays put once blocked"


def test_heavy_and_far_blocks_are_refused(world, resp):
    out = resp.grip_block("b12")                       # 4.8 kg rubble
    assert out["outcome"] == "refused" and "kg" in out["reason"]
    assert resp.grip_block("b6")["outcome"] == "refused"   # a wall
    out = resp.grip_block("b11")                       # light, but across the building
    assert out["outcome"] == "refused" and "reach" in out["reason"]
    assert resp.grip_block("nope")["outcome"] == "refused"
    assert not resp.holding("b11")


def test_supply_actions(world, resp):
    assert resp.on_action({"action": "grip", "route": "r0", "item": "radio"})["reason"] == "already carrying radio"
    placed = resp.on_action({"action": "place_supply", "route": "r0", "item": "radio"})
    assert placed["outcome"] == "done"
    assert not resp.holding("radio")
    again = resp.on_action({"action": "place_supply", "route": "r0", "item": "radio"})
    assert again["outcome"] == "refused" and "not carrying" in again["reason"]
    for _ in range(10):
        world.tick(0.1)
    assert resp.on_action({"action": "grip", "route": "r0", "item": "radio"})["outcome"] == "done"
    assert resp.holding("radio")
    dropped = resp.on_action({"action": "release", "route": "r0", "item": "water"})
    assert dropped["outcome"] == "done" and not resp.holding("water")
    for _ in range(20):
        world.tick(0.1)
    assert pos_of(world, "water")[2] < 0.1, "released water falls to the floor"


def test_planner_sequence_is_queued_behind_the_move(world, resp):
    """Planner #53 sends move -> grip -> place_supply -> release at once; sim runs them in order."""
    route(resp, "r1", demo_responder.ROUTES["r1"])
    for action in ("move", "grip", "place_supply", "release"):
        resp.on_action({"action": action, "route": "r1", "item": "water"})
    assert [e["outcome"] for e in resp.log] == ["act", "queued", "queued", "queued"]
    assert resp.holding("water"), "nothing runs before the move ends"
    drive(world, resp)
    assert resp.state == "arrived" and not resp.queue
    assert [e["outcome"] for e in resp.log[4:]] == ["done"] * 4     # arrived, grip, place, release
    assert not resp.holding("water")
    end = resp.pos[:2] + R.HALF_LEN + R.PLACE_AHEAD
    assert np.linalg.norm(pos_of(world, "water")[:2] - resp.pos[:2]) < np.linalg.norm(end - resp.pos[:2]) + 0.05


def test_world_change_drops_the_queue(world, resp):
    route(resp, "r1", demo_responder.ROUTES["r1"])
    resp.on_action({"action": "move", "route": "r1", "item": "water"})
    resp.on_action({"action": "place_supply", "route": "r1", "item": "water"})
    resp.step(0.1)
    resp.on_world_change({"kind": "aftershock", "t": 1, "moved_blocks": ["b10"]})
    assert resp.state == "frozen" and not resp.queue
    assert "dropped 1 queued" in resp.log[-1]["reason"]
    drive(world, resp, seconds=2)
    assert resp.holding("water"), "the queued place_supply never ran"


def test_unknown_route_is_refused(resp):
    out = resp.on_action({"action": "move", "route": "r404", "item": "water"})
    assert out["outcome"] == "refused" and resp.state == "idle"


def test_risky_route_needs_an_approved_gate(world, resp):
    route(resp, "r1", demo_responder.ROUTES["r1"])
    resp.on_gate_request({"id": "g1", "kind": "risky_move", "summary": "past b10", "route": "r1"})
    out = resp.on_action({"action": "move", "route": "r1", "item": "water"})
    assert out["outcome"] == "refused" and "gate" in out["reason"]
    resp.on_gate_answer({"id": "g1", "approved": False, "by": "operator"})
    assert resp.on_action({"action": "move", "route": "r1", "item": "water"})["outcome"] == "refused"
    resp.on_gate_answer({"id": "g1", "approved": True, "by": "operator"})
    assert resp.on_action({"action": "move", "route": "r1", "item": "water"})["outcome"] == "act"
    assert resp.state == "moving"


def test_world_change_freezes_and_drops_the_move(world, resp):
    route(resp, "r1", demo_responder.ROUTES["r1"])
    resp.on_action({"action": "move", "route": "r1", "item": "water"})
    for _ in range(10):
        resp.step(0.1)
        world.tick(0.1)
    resp.on_world_change({"kind": "aftershock", "t": world.t, "moved_blocks": []})
    assert resp.state == "frozen" and resp.log[-1]["outcome"] == "frozen"
    here = resp.pos
    for _ in range(10):
        resp.step(0.1)
        world.tick(0.1)
    assert np.allclose(resp.pos, here)
    assert resp.on_action({"action": "move", "route": "r1", "item": "water"})["outcome"] == "act"


def test_same_script_same_result():
    a, ra = demo_responder.run()
    b, rb = demo_responder.run()
    assert [e["reason"] for e in ra.log] == [e["reason"] for e in rb.log]
    for n in ("responder", "water", "b11"):
        assert np.allclose(pos_of(a, n), pos_of(b, n))


def test_log_decisions_match_the_contract():
    messages = pytest.importorskip("coord.messages")
    _, r = demo_responder.run()
    world = World(render=False)
    extra = R.Responder(world.m, world.d)
    extra.grip_block("b12")
    for entry in r.log + extra.log:
        messages.validate_payload("log/decision", entry)


def test_attach_wires_the_bus():
    class FakeBus:
        def __init__(self):
            self.subs, self.sent = {}, []

        def subscribe(self, topic, fn):
            self.subs.setdefault(topic, []).append(fn)

        async def publish(self, topic, data):
            self.sent.append((topic, data))
            for fn in self.subs.get(topic, []):
                fn(data)

    async def go():
        bus, world = FakeBus(), World(render=False)
        r = R.attach(world, bus)
        assert {"route/proposed", "gate/request", "gate/answer", "responder/action", "world/change"} <= set(bus.subs)
        await bus.publish("responder/action", {"action": "move", "route": "missing", "item": "water"})
        await asyncio.sleep(0)
        return r, bus

    _, bus = asyncio.run(go())
    logged = [d for t, d in bus.sent if t == "log/decision"]
    assert logged and logged[-1]["outcome"] == "refused"


def test_freezes_as_soon_as_the_shake_starts(world):
    """Review #57 follow-up 1: stop at the first tick of the aftershock, not 3 s later at world/change."""
    r = R.Responder(world.m, world.d, clock=lambda: world.t, shaking=lambda: world.shaking)
    route(r, "r1", demo_responder.ROUTES["r1"])
    r.on_action({"action": "move", "route": "r1", "item": "water"})
    r.on_action({"action": "place_supply", "route": "r1", "item": "water"})
    for _ in range(10):
        r.step(0.1)
        world.tick(0.1)
    assert world.trigger_aftershock()
    r.step(0.1)
    assert r.state == "frozen" and not r.queue and r.log[-1]["outcome"] == "frozen"
    here = r.pos
    for _ in range(10):                      # 1 s into the 3 s shake
        r.step(0.1)
        world.tick(0.1)
    assert world.shaking and np.allclose(r.pos, here)


def test_robot_geoms_are_group_3():
    """Review #57 follow-up 2: the Scout's sensors can skip robot geoms by group."""
    m, _ = scene.load()
    for g in ("responder_chassis", "responder_gripper"):
        assert m.geom_group[m.geom(g).id] == 3, g


def test_sim_loop_steps_the_responder_without_its_own_task():
    """Review #57 follow-up 3: one task (world.task) runs physics and Responder, so the hub cancels both."""
    import sim

    class Bus:
        def __init__(self):
            self.subs = {}

        def subscribe(self, topic, fn):
            self.subs.setdefault(topic, []).append(fn)

        async def publish(self, topic, data):
            for fn in self.subs.get(topic, []):
                out = fn(data)
                if asyncio.iscoroutine(out):
                    await out

    async def go():
        bus = Bus()
        world = await sim.start(bus)
        world._set_pose((-1.2, -1.7), 0.0)
        assert not hasattr(world.responder, "task")
        await bus.publish("route/proposed", {"id": "r1", "robot": "responder", "goal": "test", "model": "local-astar",
                                             "cells": R.cells_along(demo_responder.ROUTES["r1"])})
        await bus.publish("responder/action", {"action": "move", "route": "r1", "item": "water"})
        start = world.responder.pos
        await asyncio.sleep(0.5)
        moved = float(np.linalg.norm(world.responder.pos - start))
        world.task.cancel()
        await asyncio.gather(world.task, return_exceptions=True)
        after = world.responder.pos
        await asyncio.sleep(0.3)
        return moved, float(np.linalg.norm(world.responder.pos - after))

    moved, after_cancel = asyncio.run(go())
    assert moved > 0.02, "the sim loop should drive the Responder"
    assert after_cancel == 0.0, "cancelling world.task stops the Responder too"


def test_no_supply_is_placed_on_a_route_whose_move_was_refused(world, resp):
    """Real-lane run: move refused (route unknown), then place_supply must not drop water at the start."""
    for action in ("move", "place_supply", "release"):
        resp.on_action({"action": action, "route": "r9", "item": "water"})
    assert [e["outcome"] for e in resp.log] == ["refused", "refused", "refused"]
    assert resp.holding("water")


def test_responder_hears_route_proposed_before_the_physics_check():
    """sim.start: the Responder must store a route before route/verified can trigger its dispatch."""
    import sim

    class Bus:
        def __init__(self):
            self.order = []
            self.subs = {}

        def subscribe(self, topic, fn):
            self.subs.setdefault(topic, []).append(fn)
            if topic == "route/proposed":
                self.order.append(getattr(fn, "__self__", fn))

        async def publish(self, topic, data):
            pass

    async def go():
        bus = Bus()
        world = await sim.start(bus, loop=False)
        return bus, world

    bus, world = asyncio.run(go())
    assert bus.order[0] is world.responder


# ---- E2: continuous motion from sim ticks, published as responder/pose -------------------------

def _poses_during_move(world, resp, route_id, ticks):
    poses = []
    for _ in range(ticks):
        resp.step(0.1)
        world.tick(0.1)
        poses.append(resp.pose_message(world.t))
    return poses


def test_motion_is_continuous_and_speed_bounded(world, resp):
    route(resp, "r1", demo_responder.ROUTES["r1"])
    resp.on_action({"action": "move", "route": "r1", "item": "water"})
    end = R.cell_centre(resp.routes["r1"][-1])
    poses = _poses_during_move(world, resp, "r1", 40)              # 4 s of an ~20 s route
    xy = [np.array(p["pos"][:2]) for p in poses]
    steps = [float(np.linalg.norm(b - a)) for a, b in itertools.pairwise(xy)]
    assert max(steps) <= R.SPEED * 0.1 + 1e-3, "never faster than SPEED"
    assert min(steps) > 0.0, "moves on every tick while the route lasts"
    assert all(p["state"] == "moving" for p in poses)
    assert float(np.linalg.norm(xy[-1] - end)) > 1.0, "no jump to the route's end"
    # every intermediate pose lies on the route polyline (cell centres), within a few millimetres
    centres = [R.cell_centre(c) for c in resp.routes["r1"]]
    for p in xy:
        d = min(float(np.linalg.norm(p - c)) for c in centres)
        assert d <= R.RES * 0.75, d


def test_pose_message_matches_the_contract(world, resp):
    messages = pytest.importorskip("coord.messages")
    route(resp, "r1", demo_responder.ROUTES["r1"])
    resp.on_action({"action": "move", "route": "r1", "item": "water"})
    for p in _poses_during_move(world, resp, "r1", 3) + [R.Responder(world.m, world.d).pose_message(0)]:
        messages.validate_payload("responder/pose", p)


def test_revoked_permit_stops_mid_route_and_pose_holds(world, resp):
    route(resp, "r1", demo_responder.ROUTES["r1"])
    resp.on_action({"action": "move", "route": "r1", "item": "water"})
    _poses_during_move(world, resp, "r1", 10)
    resp.on_permit({"route": "r1", "granted": False, "t": world.t, "reason": "rubble shift", "evidence": []})
    held = _poses_during_move(world, resp, "r1", 10)
    assert {p["state"] for p in held} == {"frozen"}
    assert len({tuple(p["pos"]) for p in held}) == 1, "stays exactly where it stopped"


def test_blocked_route_pose_stops_short_of_the_wall(world, resp):
    route(resp, "rw", [(-0.48, -1.77), (-0.48, -0.6), (0.6, -0.6)])
    resp.on_action({"action": "move", "route": "rw", "item": "water"})
    poses = _poses_during_move(world, resp, "rw", 200)
    last = next(p for p in poses if p["state"] == "blocked")
    assert last["pos"][0] + R.HALF_LEN < -0.05, "front stays outside wall b6"
    assert poses[-1]["pos"] == last["pos"]


def test_sim_loop_publishes_a_pose_every_tick():
    import sim

    class Bus:
        def __init__(self):
            self.subs, self.poses = {}, []

        def subscribe(self, topic, fn):
            self.subs.setdefault(topic, []).append(fn)

        async def publish(self, topic, data):
            if topic == "responder/pose":
                self.poses.append(data)

    async def go():
        bus = Bus()
        world = await sim.start(bus)
        await asyncio.sleep(0.55)
        world.task.cancel()
        await asyncio.gather(world.task, return_exceptions=True)
        return bus.poses, round(world.t / 0.1)

    poses, ticks = asyncio.run(go())
    assert len(poses) >= 2 and len(poses) == ticks, "exactly one responder/pose per sim tick"
    assert [p["t"] for p in poses] == sorted(p["t"] for p in poses)
