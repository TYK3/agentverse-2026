"""#31: a triage answer chooses a routed delivery, never a route-none placement."""

import asyncio

import pytest

from perception.triage import Triager
from planner.tests.test_handoff import World, casualty, map_cells, sim_log


@pytest.fixture(autouse=True)
def off_mode(monkeypatch):
    monkeypatch.setenv("GEMINI_MODE", "off")


@pytest.mark.parametrize("triage_first", [True, False])
def test_triage_approval_starts_one_verified_delivery_in_either_subscriber_order(triage_first, caplog):
    async def scenario():
        world = World()
        triager = Triager(dialogue_reader=lambda _: None)
        if triage_first:
            triager.attach(world.bus)
        await world.start()
        world.handoff.require_triage = True
        if not triage_first:
            triager.attach(world.bus)
        await world.bus.publish("map/casualties", [casualty()])
        assert world.topics("responder/action") == [], "clinical review must not drop supplies at the start"
        assert world.topics("route/proposed") == [], "handoff waits for an accepted supply choice"
        answer = {"id": "g_triage_c1", "approved": True, "by": "operator"}
        await world.bus.publish("gate/answer", answer)
        actions = world.topics("responder/action")
        assert [a["action"] for a in actions] == ["move", "place_supply", "release"]
        route = world.topics("route/proposed")[-1]
        assert {a["route"] for a in actions} == {route["id"]}
        assert route["id"] != "none" and route["goal"] == "deliver water to c1"
        assert {a["item"] for a in actions} == {"water"}
        await world.bus.publish("gate/answer", answer)
        await world.bus.publish("map/casualties", [casualty()])
        assert world.topics("responder/action") == actions, "duplicate answers/observations cannot replay placement"
        assert not [r for r in caplog.records if r.levelname == "ERROR"]
    asyncio.run(scenario())


def test_triage_denial_stays_held_across_later_map_and_casualty_updates():
    async def scenario():
        world = await World().start()
        world.handoff.require_triage = True
        triager = Triager(dialogue_reader=lambda _: None).attach(world.bus)
        await world.bus.publish("map/casualties", [casualty()])
        await world.bus.publish("gate/answer", {"id": "g_triage_c1", "approved": False, "by": "operator"})
        await world.bus.publish("map/cells", map_cells())
        await world.bus.publish("map/casualties", [casualty()])
        assert not world.topics("responder/action")
        assert not world.topics("route/proposed")
        assert len(world.topics("gate/request")) == 1
        assert triager.summary("c1") is not None
    asyncio.run(scenario())


def test_triage_consent_never_overrides_failed_physics():
    async def scenario():
        world = await World(physics_ok=False).start()
        world.handoff.require_triage = True
        Triager(dialogue_reader=lambda _: None).attach(world.bus)
        await world.bus.publish("map/casualties", [casualty()])
        await world.bus.publish("gate/answer", {"id": "g_triage_c1", "approved": True, "by": "operator"})
        assert world.topics("route/proposed"), "consent must still enter the normal physics-checked mission"
        assert not world.topics("responder/action")
    asyncio.run(scenario())


def test_late_sim_gate_subscriber_records_navigation_approval_before_move(caplog):
    async def scenario():
        world = await World().start()
        world.loop.defer_approved_actions = True
        approved_routes = set()

        def sim_answer(data):
            request = next(r for r in world.topics("gate/request") if r["id"] == data["id"])
            if data["approved"]:
                approved_routes.add(request["route"])

        def sim_action(data):
            assert data["route"] in approved_routes, "sim must receive approval before the routed command"

        world.bus.subscribe("gate/answer", sim_answer)
        world.bus.subscribe("responder/action", sim_action)
        await world.bus.publish("map/casualties", [casualty(confidence=0.3)])
        request = world.topics("gate/request")[-1]
        await world.bus.publish("gate/answer", {"id": request["id"], "approved": True, "by": "operator"})
        await asyncio.sleep(0)
        assert [a["action"] for a in world.topics("responder/action")] == ["move", "place_supply", "release"]
        assert not [r for r in caplog.records if r.levelname == "ERROR"]
    asyncio.run(scenario())


def test_hub_planner_waits_for_an_accepted_supply_choice_and_defers_approvals():
    async def scenario():
        import planner
        from coord.hub import Bus

        bus = Bus()
        router = await planner.start(bus)
        try:
            assert router.handoff.require_triage is True
            assert router.loop.defer_approved_actions is True
            router.handoff.responder_cell = (2, 2, 0)
            await bus.publish("map/cells", map_cells())
            await bus.publish("map/casualties", [casualty()])
            assert not any(m["topic"] == "route/proposed" for m in bus.history)
            await bus.publish("casualty/triage", {"id": "c1", "injuries": [], "recommended_action": "first_aid_kit"})
            assert router.loop.mission_args["item"] == "first_aid_kit"
            assert any(m["topic"] == "route/proposed" for m in bus.history)
            assert not any(m["topic"] == "responder/action" for m in bus.history), "physics has not answered yet"
        finally:
            router.task.cancel()
            await asyncio.gather(router.task, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize("item", ["water", "first_aid_kit", "bandage"])
def test_unavailable_accepted_item_cannot_silently_become_another_supply(item):
    async def scenario():
        world = await World().start()
        world.handoff.require_triage = True
        world.handoff.kit.discard(item)
        await world.bus.publish("map/casualties", [casualty()])
        await world.bus.publish("casualty/triage", {"id": "c1", "injuries": ["reported pain"], "recommended_action": item})
        assert not world.topics("responder/action")
        assert not world.topics("route/proposed")
        assert any(d["outcome"] == "hold" and "another supply choice" in d["reason"] for d in world.handoff_logs())
    asyncio.run(scenario())


def test_world_change_discards_a_deferred_approved_dispatch():
    async def scenario():
        world = await World().start()
        world.loop.defer_approved_actions = True
        await world.bus.publish("map/casualties", [casualty(confidence=0.3)])
        request = world.topics("gate/request")[-1]
        await world.bus.publish("gate/answer", {"id": request["id"], "approved": True, "by": "operator"})
        await world.bus.publish("world/change", {"kind": "aftershock", "t": 1, "moved_blocks": ["b1"]})
        await asyncio.sleep(0)
        assert not world.topics("responder/action")
        assert any(d["outcome"] == "hold" and "stale dispatch" in d["reason"] for d in world.topics("log/decision"))
    asyncio.run(scenario())


def test_permit_freeze_keeps_the_same_delivery_without_spending_another_attempt():
    async def scenario():
        world = await World().start()
        await world.bus.publish("map/casualties", [casualty()])
        await world.bus.publish("log/decision", sim_log("frozen", "move permit revoked", at=(0.6, 0.4)))
        assert world.handoff.active == "c1"
        assert world.handoff.attempts["c1"] == 1
        assert not world.handoff.waiting_scan and "c1" not in world.handoff.skipped
        await world.bus.publish("map/cells", map_cells())
        assert len(world.topics("route/proposed")) == 1, "a safety pause must not start a competing handoff mission"
    asyncio.run(scenario())


def test_replan_starts_from_the_measured_responder_pose():
    async def scenario():
        world = await World().start()
        await world.bus.publish("map/casualties", [casualty()])
        await world.bus.publish("responder/pose", {"t": 2, "pos": [0.7, 0.4, 0.08], "yaw": 0,
                                                   "state": "moving", "route": "r1", "carrying": ["water"]})
        await world.bus.publish("world/change", {"kind": "block_added", "t": 2, "moved_blocks": ["x1"]})
        await world.bus.publish("map/cells", map_cells())
        assert world.topics("route/proposed")[-1]["cells"][0] == [14, 8, 0]
        assert world.handoff.active == "c1" and world.handoff.attempts["c1"] == 1
    asyncio.run(scenario())


def test_fresh_permit_rechecks_the_paused_delivery_from_its_current_pose():
    async def scenario():
        world = await World().start()
        await world.bus.publish("map/casualties", [casualty()])
        await world.bus.publish("responder/pose", {"t": 2, "pos": [0.7, 0.4, 0.08], "yaw": 0,
                                                   "state": "frozen", "route": "r1", "carrying": ["water"]})
        await world.bus.publish("log/decision", sim_log("frozen", "move permit revoked", at=(0.7, 0.4)))
        await world.bus.publish("permit/route", {"route": "r1", "granted": False, "t": 2,
                                                "reason": "sensed shift", "evidence": []})
        before = len(world.topics("route/proposed"))
        assert before == 1
        await world.bus.publish("permit/route", {"route": "r1", "granted": True, "t": 3,
                                                "reason": "fresh scan", "evidence": []})
        await asyncio.sleep(0)
        route = world.topics("route/proposed")[-1]
        assert len(world.topics("route/proposed")) == 2 and route["id"] != "r1"
        assert route["cells"][0] == [14, 8, 0]
        assert world.topics("responder/action")[-1]["route"] == route["id"]
        assert world.handoff.active == "c1" and world.handoff.attempts["c1"] == 1
    asyncio.run(scenario())


def test_a_new_unseen_pose_cannot_replan_from_the_old_safe_start():
    async def scenario():
        world = await World().start()
        await world.bus.publish("map/casualties", [casualty()])
        before = len(world.topics("responder/action"))
        await world.bus.publish("responder/pose", {"t": 2, "pos": [10, 10, 0.08], "yaw": 0,
                                                   "state": "frozen", "route": "r1", "carrying": ["water"]})
        await world.bus.publish("world/change", {"kind": "block_added", "t": 2, "moved_blocks": ["x1"]})
        await world.bus.publish("map/cells", map_cells())
        assert world.loop.mission_args["start"] == (200, 200, 0)
        assert len(world.topics("responder/action")) == before
        assert world.loop.waiting_scan
    asyncio.run(scenario())
