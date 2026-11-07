"""T15 checks: a full cycle with the link down uses only local compute, the re-check when it
returns, goal reading by the local model (and its keyword stand-in), the budget meter, the toggle."""

import asyncio
import json

from planner import budget as B
from planner import link_toggle, local_llm
from planner import loop as L
from planner.tests.test_loop import START, Gem, setup, two_gap_map, verify

PLACES = {"back room": [8, 3, 0], "left room": [8, 6, 0], "corridor": [2, 0, 0]}


def link(bus, online):
    asyncio.run(link_toggle.set_link(bus, online))


def test_offline_cycle_is_local_only_and_rechecked_when_the_link_returns():
    gem = Gem()  # live Gemini available, but the link is down
    bus, lp, _ = setup(gem=gem)
    link(bus, False)
    assert bus.of("log/decision")[-1]["outcome"] == "offline" and not lp.online
    verify(bus, "r1", True)
    d = bus.of("gate/decision")[-1]
    assert d["outcome"] == "act" and "skipped (offline" in d["reason"]
    assert gem.asked == [] and bus.of("responder/action")
    assert {p["model"] for p in bus.of("route/proposed")} == {"local-astar"}
    link(bus, True)
    logs = bus.of("log/decision")
    assert logs[-2]["outcome"] == "online" and "1 route(s)" in logs[-2]["reason"]
    assert logs[-1]["outcome"] == "recheck agrees" and logs[-1]["model"] == "gemini-4-argon"
    assert gem.asked == ["lead_reasoning"] and lp.offline_acts == []


def test_recheck_disagreement_refers_the_running_route():
    bus, _lp, _ = setup(gem=Gem('{"agree": false, "why": "slab moved over the gap"}'))
    link(bus, False)
    verify(bus, "r1", True)
    link(bus, True)
    assert bus.of("log/decision")[-2]["outcome"] == "recheck disagrees"
    assert bus.of("gate/decision")[-1]["outcome"] == "refer" and bus.of("gate/request")


def test_repeated_link_messages_log_once():
    bus, _lp, _ = setup()
    n = len(bus.of("log/decision"))
    link(bus, True)
    link(bus, False)
    link(bus, False)
    assert len(bus.of("log/decision")) == n + 1


def test_keyword_stand_in_resolves_a_change_of_mind(monkeypatch):
    monkeypatch.setattr(local_llm, "HOST", "127.0.0.1:9")  # nothing listens: runtime unavailable
    got = local_llm.interpret("send the first aid kit to the left room, no, the back room", list(PLACES))
    assert got == {"place": "back room", "item": "first_aid_kit", "model": "keyword-stand-in",
                   "why": "keyword match (local model unavailable)"}
    assert local_llm.interpret("go somewhere", list(PLACES))["place"] is None


def test_local_model_reply_is_used_only_when_it_names_a_known_place(monkeypatch):
    replies = iter(['{"place": "back room", "item": "radio", "why": "final choice"}',
                    '{"place": "the moon", "item": "radio", "why": "?"}'])
    monkeypatch.setattr(local_llm, "ask", lambda *a, **k: next(replies))
    assert local_llm.interpret("radio to the back room", list(PLACES)) == {
        "place": "back room", "item": "radio", "why": "final choice", "model": "gemma-4-local"}
    assert local_llm.interpret("radio to the corridor", list(PLACES))["model"] == "keyword-stand-in"


def command_setup():
    bus, lp, _ = setup()
    lp.places, lp.start_cell = PLACES, lambda: START
    lp.interpret = lambda text, names: {"place": "back room", "item": "radio", "why": "said back room",
                                        "model": "gemma-4-local"}
    return bus, lp


def say(bus, text):
    asyncio.run(bus.publish("operator/command", {"text": text, "source": "voice"}))


def test_operator_command_becomes_a_mission_read_by_the_local_model():
    bus, _lp = command_setup()
    say(bus, "send the radio to the left room, no, the back room")
    goal_log = next(d for d in bus.of("log/decision") if d["outcome"] == "goal")
    assert goal_log["model"] == "gemma-4-local" and "radio to back room" in goal_log["reason"]
    r = bus.of("route/proposed")[-1]
    assert r["cells"][-1] == PLACES["back room"] and r["goal"] == "deliver radio to back room"
    assert r["model"] == "local-astar"  # the model reads the goal; A* still makes the route


def test_scan_and_stop_commands():
    bus, lp = command_setup()
    say(bus, "scan the back room")
    assert bus.of("scout/goto")[-1]["reason"] == "operator asked to scan back room"
    say(bus, "stop")
    assert lp.state == L.IDLE and bus.of("log/decision")[-1]["outcome"] == "hold"


def test_budget_message_shape_and_step_timing():
    bus, _, _ = setup()
    ticks = iter([0.0, 0.012, 1.0, 1.003])
    b = B.Budget(bus, model_mb=lambda: 4500.0, clock=lambda: next(ticks))
    with b.step():
        pass
    with b.step():
        pass
    msg = b.message()
    assert msg["ms_per_step"] == 12.0 and msg["model"] == "gemma-4-e2b"
    assert msg["mem_mb"] > 4500 and msg["limit"] == B.CONFIG["limit"]
    assert msg["device"] == B.CONFIG["device"]
    assert b.message()["ms_per_step"] == 12.0  # holds the last window when no step ran
    assert B.Budget(bus, model_mb=lambda: 0.0).message()["model"] == "gemma-4-e2b (not loaded)"
    asyncio.run(bus.publish("status/budget", msg))  # schema-checked when coord.messages is present


def test_loop_times_its_steps_into_the_budget():
    bus, lp, _ = setup()
    lp.budget = B.Budget(bus, model_mb=lambda: 0.0)
    verify(bus, "r1", False, [(4, 1, 0)])  # one re-plan step
    verify(bus, "r2", True)  # one gate step
    assert len(lp.budget.steps) == 2 and all(ms < B.CONFIG["limit"]["ms_per_step"] for ms in lp.budget.steps)


def test_start_publishes_budget_every_second():
    async def go():
        bus = __import__("planner.tests.test_loop", fromlist=["Bus"]).Bus()
        lp = await L.start(bus, gem=Gem())
        await bus.publish("map/cells", two_gap_map())
        await asyncio.sleep(0.05)
        lp.task.cancel()
        return bus
    bus = asyncio.run(go())
    assert bus.of("status/budget") and json.dumps(bus.of("status/budget")[0])


def test_hub_entry_point_wires_loop_and_budget():
    import planner
    from planner.tests.test_loop import Bus

    async def go():
        bus = Bus()
        router = await planner.start(bus)
        await bus.publish("map/cells", two_gap_map())
        await bus.publish("map/hazards", [])
        await router.loop.mission(START, (8, 3, 0), casualty=None)
        await asyncio.sleep(0.05)
        router.task.cancel()
        return bus
    bus = asyncio.run(go())
    assert bus.of("route/proposed") and bus.of("status/budget")
