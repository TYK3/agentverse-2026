"""RADIO-HAS-FLOOR: every radio delivery in a real run log can be placed on its floor (ref RADIO-HAS-FLOOR).

A delivery is a Responder `log/decision` with outcome "done" whose reason is "placed radio at [x, y]"
(sim/responder.py). Its floor comes from the log: the Responder's latest `responder/pose` by sim time at
or before the delivery (sim.run publishes one every tick, E2; file order differs, since the Responder
publishes its log/decision from a task) gives its height; minus the Responder's ride height
(RIDE) that is a floor height, which must be one of the building's floors (FLOOR_Z, within Z_TOL).

Finding: the delivery record itself names no floor (no floor field, and the reason gives only x, y).
That is pinned as a strict xfail: it fails (XPASS) the day the Responder writes the floor, and the mark
must then come off. B1 and lower have no Responder or kit yet (#267), so real deliveries are at ground.

Real log: REAL, the bus messages of a real delivery of the radio: the sim (sim.start: MuJoCo world,
physics check, Responder) and the planner loop on one in-process bus, as tools/tests/test_deliver.py,
the operator approving the gate, the Responder's own E2 pose message each tick (kept: the first poses
and those from 22.0 s to the delivery at 22.6 s). A fresh live run is checked too when MuJoCo is
installed (it skips in CI).
"""

import asyncio
import re

import pytest

ITEM = 'radio'
FLOOR_Z = {"L1": 0.6, "ground": 0.0, "B1": -0.6, "B2": -1.2, "B3": -1.8}   # sim/levels.py LEVEL_Z
RIDE = 0.05                        # the Responder's origin sits this far above the floor (sim/scenes)
Z_TOL = 0.1
PLACED = re.compile(r"^placed (\w+) at \[")

REAL = [
    {'topic': 'scene/loaded', 'data': {'scene': 'backup', 'blocks': 16}},
    {'topic': 'gate/request', 'data': {'id': 'g1', 'kind': 'risky_move', 'route': 'r1', 'summary': 'deliver radio to c1 via r1: 82/82 route cells seen, casualty c1 confidence 0.40'}},
    {'topic': 'gate/answer', 'data': {'id': 'g1', 'approved': True, 'by': 'operator'}},
    {'topic': 'responder/action', 'data': {'action': 'move', 'route': 'r1', 'item': 'radio'}},
    {'topic': 'responder/action', 'data': {'action': 'place_supply', 'route': 'r1', 'item': 'radio'}},
    {'topic': 'responder/action', 'data': {'action': 'release', 'route': 'r1', 'item': 'radio'}},
    {'topic': 'responder/pose', 'data': {'t': 0.1, 'pos': [-0.48, -1.774, 0.05], 'yaw': -0.197, 'state': 'moving', 'route': 'r1', 'carrying': ['water', 'first_aid_kit', 'radio', 'bandage', 'splint', 'thermal_blanket']}},
    {'topic': 'log/decision', 'data': {'t': 0.0, 'perception': 'responder at [-0.5, -1.77], move r1', 'model': 'sim', 'physics': 'mujoco', 'outcome': 'act', 'reason': 'following route r1, 82 cells'}},
    {'topic': 'log/decision', 'data': {'t': 0.0, 'perception': 'responder at [-0.5, -1.77]', 'model': 'sim', 'physics': 'mujoco', 'outcome': 'queued', 'reason': 'place_supply radio waits for the current move (1 queued)'}},
    {'topic': 'log/decision', 'data': {'t': 0.0, 'perception': 'responder at [-0.5, -1.77]', 'model': 'sim', 'physics': 'mujoco', 'outcome': 'queued', 'reason': 'release radio waits for the current move (2 queued)'}},
    {'topic': 'responder/pose', 'data': {'t': 0.2, 'pos': [-0.475, -1.76, 0.05], 'yaw': 1.571, 'state': 'moving', 'route': 'r1', 'carrying': ['water', 'first_aid_kit', 'radio', 'bandage', 'splint', 'thermal_blanket']}},
    {'topic': 'responder/pose', 'data': {'t': 22.0, 'pos': [1.667, 0.675, 0.05], 'yaw': 0.0, 'state': 'moving', 'route': 'r1', 'carrying': ['water', 'first_aid_kit', 'radio', 'bandage', 'splint', 'thermal_blanket']}},
    {'topic': 'responder/pose', 'data': {'t': 22.1, 'pos': [1.687, 0.675, 0.05], 'yaw': 0.0, 'state': 'moving', 'route': 'r1', 'carrying': ['water', 'first_aid_kit', 'radio', 'bandage', 'splint', 'thermal_blanket']}},
    {'topic': 'responder/pose', 'data': {'t': 22.2, 'pos': [1.707, 0.675, 0.05], 'yaw': 0.0, 'state': 'moving', 'route': 'r1', 'carrying': ['water', 'first_aid_kit', 'radio', 'bandage', 'splint', 'thermal_blanket']}},
    {'topic': 'responder/pose', 'data': {'t': 22.3, 'pos': [1.726, 0.674, 0.05], 'yaw': -0.785, 'state': 'moving', 'route': 'r1', 'carrying': ['water', 'first_aid_kit', 'radio', 'bandage', 'splint', 'thermal_blanket']}},
    {'topic': 'responder/pose', 'data': {'t': 22.4, 'pos': [1.74, 0.66, 0.05], 'yaw': -0.785, 'state': 'moving', 'route': 'r1', 'carrying': ['water', 'first_aid_kit', 'radio', 'bandage', 'splint', 'thermal_blanket']}},
    {'topic': 'responder/pose', 'data': {'t': 22.5, 'pos': [1.755, 0.645, 0.05], 'yaw': -0.785, 'state': 'moving', 'route': 'r1', 'carrying': ['water', 'first_aid_kit', 'radio', 'bandage', 'splint', 'thermal_blanket']}},
    {'topic': 'responder/pose', 'data': {'t': 22.6, 'pos': [1.769, 0.631, 0.05], 'yaw': -0.785, 'state': 'moving', 'route': 'r1', 'carrying': ['water', 'first_aid_kit', 'radio', 'bandage', 'splint', 'thermal_blanket']}},
    {'topic': 'responder/pose', 'data': {'t': 22.7, 'pos': [1.775, 0.625, 0.05], 'yaw': -0.785, 'state': 'arrived', 'route': 'r1', 'carrying': ['water', 'first_aid_kit', 'bandage', 'splint', 'thermal_blanket']}},
    {'topic': 'log/decision', 'data': {'t': 22.6, 'perception': 'responder at [1.78, 0.62], move r1', 'model': 'sim', 'physics': 'mujoco', 'outcome': 'done', 'reason': 'arrived at the end of route r1'}},
    {'topic': 'log/decision', 'data': {'t': 22.6, 'perception': 'responder at [1.78, 0.62], place_supply radio', 'model': 'sim', 'physics': 'mujoco', 'outcome': 'done', 'reason': 'placed radio at [1.94, 0.46]'}},
    {'topic': 'log/decision', 'data': {'t': 22.6, 'perception': 'responder at [1.78, 0.62], release radio', 'model': 'sim', 'physics': 'mujoco', 'outcome': 'done', 'reason': 'gripper open, not holding radio'}},
]


def deliveries(messages):
    """[(t, item, floor named in the record or None, floor from the last pose or None)]."""
    # By sim time, not file order: the Responder publishes its log/decision from a task, so a delivery
    # at 22.6 s can reach the bus after the 22.7 s pose.
    poses = sorted((m["data"]["t"], m["data"]["pos"]) for m in messages
                   if m.get("topic") == "responder/pose" and isinstance(m.get("data"), dict))
    out = []
    for m in messages:
        topic, d = m.get("topic"), m.get("data") or {}
        if topic != "log/decision" or d.get("outcome") != "done":
            continue
        hit = PLACED.match(d.get("reason", ""))
        if not hit:
            continue
        named = d.get("floor") or d.get("level")
        before = [pos for t, pos in poses if t <= d["t"] + 1e-6]
        floor = None
        if before:
            z = before[-1][2] - RIDE
            floor = next((f for f, fz in FLOOR_Z.items() if abs(z - fz) <= Z_TOL), None)
        out.append((d["t"], hit.group(1), named, floor))
    return out


def check(messages):
    got = [x for x in deliveries(messages) if x[1] == ITEM]
    assert got, f"no {ITEM} delivery in this log"
    unplaced = [x for x in got if x[3] is None]
    assert unplaced == [], f"{ITEM} delivery with no floor from the log: {unplaced}"
    return got


def test_real_delivery_is_placed_on_its_floor():
    got = check(REAL)
    assert got == [(22.6, ITEM, None, "ground")]
    assert [a["action"] for a in (m["data"] for m in REAL if m["topic"] == "responder/action")] == [
        "move", "place_supply", "release"]


@pytest.mark.xfail(strict=True, reason="the delivery record names no floor; it only gives x, y (finding)")
def test_the_delivery_record_names_its_floor():
    assert all(named in FLOOR_Z for _, _, named, _ in check(REAL))


def test_a_fresh_real_delivery():
    pytest.importorskip("mujoco")
    import sim
    from planner import loop as L
    from planner.route import RoutePlanner
    from planner.tests.test_loop import Bus, Clock, OffGem
    from tools.tests.test_deliver import C1, GOAL, START, cell, map_from_blocks

    async def go():
        bus, clock = Bus(), Clock()
        world = await sim.start(bus, loop=False)
        world._set_pose((-1.2, -1.7), 0.0)
        router = RoutePlanner(bus)
        bus.subscribe("map/cells", router.update_map)
        lp = L.Loop(bus, router, gem=OffGem(), clock=clock, review_timeout=5.0).attach()
        await bus.publish("map/cells", map_from_blocks(bus.of("scene/loaded")[0]["blocks"]))
        await bus.publish("map/hazards", [])
        await bus.publish("map/casualties", [C1])
        await lp.mission(cell(*START), cell(*GOAL), goal_text=f"deliver {ITEM} to c1", item=ITEM)
        (req,) = bus.of("gate/request")
        await bus.publish("gate/answer", {"id": req["id"], "approved": True, "by": "operator"})
        r = world.responder
        for _ in range(600):
            r.step(0.1)
            world.tick(0.1)
            await bus.publish("responder/pose", r.pose_message(world.t))
            await asyncio.sleep(0)
            if r.state != "moving" and not r.queue:
                break
        return [{"topic": t, "data": d} for t, d in bus.sent]

    got = check(asyncio.run(go()))
    assert [(item, floor) for _, item, _, floor in got] == [(ITEM, "ground")]


def _msgs(z=0.05, pose_t=22.5, item=ITEM):
    return [{"topic": "responder/pose", "data": {"t": pose_t, "pos": [1.775, 0.625, z], "state": "arrived"}},
            {"topic": "log/decision", "data": {"t": 22.6, "outcome": "done", "model": "sim",
                                               "reason": f"placed {item} at [1.94, 0.46]"}}]


@pytest.mark.parametrize("messages", [
    _msgs()[1:],                       # no pose before the delivery
    _msgs(pose_t=23.0),                # the only pose comes after it
    _msgs(z=-0.25),                    # half way between ground and B1: no floor
    _msgs(item="water"),               # not this item: no radio delivery at all
])
def test_unplaceable_or_missing_deliveries_fail(messages):
    with pytest.raises(AssertionError):
        check(messages)


def test_a_delivery_on_b1_would_be_placed_on_b1():
    assert check(_msgs(z=-0.6 + RIDE))[0][3] == "B1"
