"""T13 checks: propose, verify fail, re-plan, verify ok, each gate band, the human gate,
the online review (agree, disagree, timeout, off) and the visible re-plan on world/change."""

import asyncio
import time

import pytest

from planner import loop as L
from planner.route import RoutePlanner

try:  # the hub's schemas (#10); when present every published payload is validated
    from coord.messages import validate_payload
except ImportError:
    validate_payload = None

START, GOAL = (0, 3, 0), (8, 3, 0)


def two_gap_map(unknown=()):
    """9 x 7 room, wall at x=4 with gaps at y=1 and y=5. Cells in `unknown` are reported unknown."""
    cells = []
    for x in range(9):
        for y in range(7):
            wall = x == 4 and y not in (1, 5)
            state = "unknown" if (x, y) in unknown else "seen"
            cells.append({"cell": [x, y, 0], "state": state, "occupied": wall and state == "seen"})
    return {"t": 0, "res": 0.1, "cells": cells}


CASUALTY = {"id": "c1", "pos": [0.85, 0.35, 0], "confidence": 0.9, "clues": ["thermal", "sound"],
            "vitals": {"breathing_rate": 14, "simulated": True}}


class Bus:
    def __init__(self):
        self.subs, self.sent = {}, []

    def subscribe(self, topic, fn):
        self.subs.setdefault(topic, []).append(fn)

    async def publish(self, topic, data):
        if validate_payload:
            validate_payload(topic, data)
        self.sent.append((topic, data))
        for fn in self.subs.get(topic, []):
            r = fn(data)
            if asyncio.iscoroutine(r):
                await r

    def of(self, topic):
        return [d for t, d in self.sent if t == topic]


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Gem:
    MODE = "live"

    def __init__(self, reply='{"agree": true, "why": "clear"}', delay=0.0):
        self.reply, self.delay, self.asked, self.stand_ins = reply, delay, [], set()

    def ask(self, model_key, prompt, **kw):
        self.asked.append(model_key)
        time.sleep(self.delay)
        return self.reply

    def mark_stand_in(self, feature):
        self.stand_ins.add(feature)


class OffGem(Gem):
    MODE = "off"


def setup(gem=None, casualty=CASUALTY, unknown=(), timeout=5.0):
    bus, clock = Bus(), Clock()
    router = RoutePlanner(bus)
    bus.subscribe("map/cells", router.update_map)
    lp = L.Loop(bus, router, gem=gem or OffGem(), clock=clock, review_timeout=timeout).attach()

    async def go():
        await bus.publish("map/cells", two_gap_map(unknown))
        await bus.publish("map/hazards", [])
        if casualty:
            await bus.publish("map/casualties", [casualty])
        await lp.mission(START, GOAL)
    asyncio.run(go())
    return bus, lp, clock


def verify(bus, rid, ok, cells=(), detail=""):
    asyncio.run(bus.publish("route/verified", {"id": rid, "ok": ok, "unstable_cells": [list(c) for c in cells],
                                               "detail": detail}))


def test_gate_bands():
    assert L.gate_outcome(0.95) == L.gate_outcome(0.8) == "act"
    assert L.gate_outcome(0.79) == L.gate_outcome(0.5) == "relook"
    assert L.gate_outcome(0.49) == L.gate_outcome(0.0) == "refer"


def test_propose_verify_fail_replan_verify_ok_then_act():
    bus, lp, _ = setup()
    r1 = bus.of("route/proposed")[0]
    assert lp.state == L.PROPOSED and r1["model"] == "local-astar"
    gap = next(c for c in r1["cells"] if c[0] == 4)
    verify(bus, "r1", False, [gap], "block b7 falls")
    r2 = bus.of("route/proposed")[1]
    assert r2["id"] == "r2" and gap not in r2["cells"]  # the re-plan avoids the unstable gap
    assert any(d["outcome"] == "replanning" and "b7" in d["physics"] for d in bus.of("log/decision"))
    verify(bus, "r2", True, detail="stable")
    decision = bus.of("gate/decision")[-1]
    assert decision["outcome"] == "act" and decision["confidence"] == 0.9
    assert lp.state == L.EXECUTING
    assert bus.of("responder/action") == [{"action": "move", "route": "r2", "item": "water"}]
    assert "stand-in (gemini off)" in decision["reason"]


def test_ignores_verdicts_for_other_routes():
    bus, lp, _ = setup()
    verify(bus, "r9", False, [(4, 1, 0)])
    assert lp.state == L.PROPOSED and len(bus.of("route/proposed")) == 1


def test_relook_band_sends_scout_to_the_weakest_cell():
    bus, lp, _ = setup(casualty={**CASUALTY, "confidence": 0.6})
    verify(bus, "r1", True)
    d = bus.of("gate/decision")[-1]
    assert d["outcome"] == "relook" and d["confidence"] == 0.6
    assert bus.of("scout/goto")[-1]["target"] == [0.85, 0.35, 0.05]  # centre of the goal cell
    assert not bus.of("responder/action") and lp.waiting_scan


def test_refer_band_asks_a_human_and_acts_only_on_approval():
    bus, lp, _ = setup(casualty={**CASUALTY, "confidence": 0.3})
    verify(bus, "r1", True)
    assert bus.of("gate/decision")[-1]["outcome"] == "refer"
    req = bus.of("gate/request")[-1]
    assert req["kind"] == "risky_move" and req["route"] == "r1"
    assert not bus.of("responder/action")
    asyncio.run(bus.publish("gate/answer", {"id": req["id"], "approved": True, "by": "operator"}))
    assert bus.of("responder/action")[-1]["route"] == "r1" and lp.state == L.EXECUTING


def test_rejected_refer_holds():
    bus, lp, _ = setup(casualty={**CASUALTY, "confidence": 0.3})
    verify(bus, "r1", True)
    req = bus.of("gate/request")[-1]
    asyncio.run(bus.publish("gate/answer", {"id": req["id"], "approved": False, "by": "operator"}))
    assert not bus.of("responder/action") and lp.state == L.IDLE


def test_unseen_route_cells_lower_confidence():
    bus, _lp, _ = setup()
    asyncio.run(bus.publish("map/cells", {"t": 1, "res": 0.1, "cells": [
        {"cell": c, "state": "unknown", "occupied": False} for c in bus.of("route/proposed")[0]["cells"][1:4]]}))
    verify(bus, "r1", True)
    d, cells = bus.of("gate/decision")[-1], bus.of("route/proposed")[0]["cells"]
    assert d["outcome"] == "relook" and d["confidence"] == round(1 - 3 / len(cells), 3)
    i, j, _ = cells[1]  # the first unseen route cell is the weakest link
    assert bus.of("scout/goto")[-1]["target"] == [round((i + .5) * .1, 3), round((j + .5) * .1, 3), 0.05]


def test_too_many_physics_failures_refer():
    bus, _lp, _ = setup()
    for n in range(1, 5):
        rid = bus.of("route/proposed")[-1]["id"]
        verify(bus, rid, False, [], "unstable slab")  # no cells: only the count can refer
        if n <= L.MAX_REPLANS:
            assert bus.of("route/proposed")[-1]["id"] == f"r{n + 1}"
    assert bus.of("gate/decision")[-1]["outcome"] == "refer" and bus.of("gate/request")


def test_no_route_re_looks_at_frontier():
    bus, lp, _ = setup()
    verify(bus, "r1", False, [(4, 1, 0), (4, 5, 0)], "both gaps unstable")
    assert bus.of("gate/decision")[-1]["outcome"] == "relook"
    assert bus.of("scout/goto") and lp.state == L.IDLE and lp.waiting_scan


def test_world_change_drops_route_waits_for_rescan_and_replans_with_reason():
    bus, lp, clock = setup()
    verify(bus, "r1", True)
    assert lp.state == L.EXECUTING
    asyncio.run(bus.publish("world/change", {"kind": "aftershock", "t": 30, "moved_blocks": ["b7"]}))
    log = bus.of("log/decision")[-1]
    assert log["outcome"] == "replanning" and "aftershock moved b7" in log["perception"]
    assert "Responder held" in log["reason"] and lp.state == L.IDLE
    n = len(bus.of("route/proposed"))
    # Perception marks the moved area unknown; the next map update triggers a new route.
    clock.now = 2.0
    asyncio.run(bus.publish("map/cells", {"t": 32, "res": 0.1, "cells": [
        {"cell": [4, 1, 0], "state": "unknown", "occupied": False}]}))
    r = bus.of("route/proposed")[n]
    assert [4, 1, 0] not in r["cells"]
    assert "map re-scanned after aftershock moved b7" in bus.of("log/decision")[-1]["perception"]
    assert bus.of("log/decision")[-1]["reason"].startswith(f"route {r['id']}")


def test_replan_after_rescan_is_throttled():
    bus, _lp, clock = setup()
    verify(bus, "r1", False, [(4, 1, 0), (4, 5, 0)])  # no route: waiting for the scan
    clock.now = 5.0
    cells = {"t": 1, "res": 0.1, "cells": []}
    asyncio.run(bus.publish("map/cells", cells))
    asyncio.run(bus.publish("map/cells", cells))  # same second: no second attempt
    assert len(bus.of("scout/goto")) == 2


def test_online_review_agrees_and_is_logged():
    gem = Gem()
    bus, _lp, _ = setup(gem=gem)
    verify(bus, "r1", True)
    assert gem.asked == ["lead_reasoning"]
    assert "online review agrees" in bus.of("gate/decision")[-1]["reason"]
    assert "gemini-4-argon" in bus.of("log/decision")[-1]["model"]


def test_online_review_disagreement_refers():
    bus, _lp, _ = setup(gem=Gem('```json\n{"agree": false, "why": "slab above the gap"}\n```'))
    verify(bus, "r1", True)
    d = bus.of("gate/decision")[-1]
    assert d["outcome"] == "refer" and "slab above the gap" in d["reason"]
    assert not bus.of("responder/action")


@pytest.mark.parametrize("gem", [Gem(delay=0.3), Gem("not json")])
def test_online_review_timeout_or_bad_reply_is_skipped_and_acts(gem):
    bus, _lp, _ = setup(gem=gem, timeout=0.05)
    verify(bus, "r1", True)
    assert "online review skipped" in bus.of("gate/decision")[-1]["reason"]
    assert bus.of("responder/action")


def test_gemini_off_marks_the_stand_in():
    gem = OffGem()
    bus, _lp, _ = setup(gem=gem)
    verify(bus, "r1", True)
    assert gem.asked == [] and gem.stand_ins == {"route_review"}
