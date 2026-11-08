"""HANDOFF-START-FIX: the handoff plans from where the Responder really is (responder/pose), not
from backup.xml's hard-coded start, and sends the Scout to map the Responder's area when no seen
free cell is near it. Before the fix, in the building scene, the Responder stayed idle all run:
every dispatch planned from RESPONDER_START, found no start cell and re-looked at the casualty."""

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("fastapi")

from planner import handoff as H
from planner.tests.test_handoff import RES, World, casualty, run


def pose(x, y, state="idle"):
    return {"t": 0.1, "pos": [x, y, 0.05], "yaw": 1.571, "state": state, "route": None,
            "carrying": ["water", "first_aid_kit", "radio"]}


def test_route_starts_from_the_responder_pose_not_the_constructor_default():
    async def go():
        w = await World().start(start_cell=(2, 2, 0))
        await w.bus.publish("responder/pose", pose(0.62, 0.62))     # cell (12, 12)
        await w.bus.publish("map/casualties", [casualty(confidence=0.9)])
        return w

    w = run(go())
    assert w.handoff.responder_cell == (12, 12, 0)
    routes = w.topics("route/proposed")
    assert routes, "a mission starts once the Responder's real cell is on the map"
    assert routes[0]["cells"][0] == [12, 12, 0]


def test_responder_off_the_seen_map_sends_the_scout_to_the_responder():
    async def go():
        # The room's seen cells end at x 1.95 m; the Responder stands 1 m past them.
        w = await World().start(start_cell=(2, 2, 0))
        await w.bus.publish("responder/pose", pose(3.0, 1.0))
        await w.bus.publish("map/casualties", [casualty(confidence=0.9)])
        return w

    w = run(go())
    assert w.handoff.start_cell() is None
    assert w.topics("responder/action") == [], "no route without a start cell"
    goto = w.topics("scout/goto")
    assert goto, "the Scout is sent to map the Responder's area"
    tx, ty, _ = goto[-1]["target"]
    assert abs(tx - 3.0) <= 2 * RES and abs(ty - 1.0) <= 2 * RES, goto[-1]
    assert "Responder" in goto[-1]["reason"]
    looks = [d for d in w.handoff_logs("relook") if "Responder" in d["reason"]]
    assert looks, w.handoff_logs()


def test_pose_updates_do_not_dispatch_every_tick():
    async def go():
        w = await World().start(start_cell=(2, 2, 0))
        for _ in range(20):
            await w.bus.publish("responder/pose", pose(3.0, 1.0))
        return w

    w = run(go())
    assert w.topics("scout/goto") == [] and w.handoff_logs() == []


def test_responder_look_is_rate_limited():
    async def go():
        w = await World().start(start_cell=(2, 2, 0))
        await w.bus.publish("responder/pose", pose(3.0, 1.0))
        for _ in range(5):
            await w.bus.publish("map/casualties", [casualty(confidence=0.9)])
        return w

    w = run(go())
    to_responder = [g for g in w.topics("scout/goto") if "Responder" in g["reason"]]
    assert len(to_responder) == 1, f"one look per {H.LOOK_EVERY_S} s, got {len(to_responder)}"


def test_responder_on_unmapped_ground_starts_from_the_nearest_seen_free_cell():
    # Building scene: the Responder waits outside on open ground, where LiDAR rays get no return
    # and leave no cells, 0.58 m from the first seen free cell. Here: nothing is mapped within
    # START_SNAP_M of (2.7, 1.0); the room's seen free cells end at x 1.95 m (0.75 m away).
    async def go():
        w = await World().start(start_cell=(2, 2, 0))
        await w.bus.publish("responder/pose", pose(2.72, 1.02))     # cell (54, 20)
        await w.bus.publish("map/casualties", [casualty(confidence=0.9)])
        return w

    w = run(go())
    assert w.handoff.start_cell() == (39, 20, 0)
    routes = w.topics("route/proposed")
    assert routes and routes[0]["cells"][0] == [39, 20, 0]
    assert [a["action"] for a in w.topics("responder/action")][:1] == ["move"]


def test_mapped_rubble_round_the_responder_keeps_the_short_snap():
    # Cells near the Responder are mapped (unknown and occupied ones): it is not on open ground,
    # so the longer reach does not apply and no route starts through the rubble.
    rubble = [(i, j) for i in range(33, 40) for j in range(10, 31)]

    async def go():
        w = await World().start(start_cell=(2, 2, 0), occupied=rubble)
        await w.bus.publish("responder/pose", pose(2.27, 1.02))     # cell (45, 20), beside mapped cells
        await w.bus.publish("map/casualties", [casualty(confidence=0.9)])
        return w

    w = run(go())
    assert w.handoff.start_cell() is None
    assert w.topics("route/proposed") == []
