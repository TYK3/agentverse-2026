"""X3 checks: the Scout hands casualties to the Responder, the work is re-split when either robot is
blocked, and a human is asked only when confidence is low. Runs on the real validating hub Bus."""

import asyncio

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("fastapi")

from coord.hub import Bus
from planner import handoff as H
from planner import loop as L
from planner.route import RoutePlanner

RES = 0.05
SEEN = 40        # cells 0..39 in x and y are seen and free (a 2 m x 2 m room)
UNKNOWN = 6      # cells 40..45 in x are listed as unknown, so frontiers exist east of the room


def map_cells(occupied=()):
    cells = []
    for i in range(SEEN + UNKNOWN):
        for j in range(SEEN):
            state = "seen" if i < SEEN else "unknown"
            cells.append({"cell": [i, j, 0], "state": state, "occupied": (i, j) in occupied})
    return {"t": 0, "res": RES, "cells": cells}


def casualty(cid="c1", pos=(1.5, 1.5, 0.1), confidence=0.9):
    return {"id": cid, "pos": list(pos), "confidence": confidence, "clues": ["thermal", "sound"],
            "vitals": {"breathing_rate": 14, "simulated": True}}


def scout_frame(pos, state="moving", target=None):
    return {"t": 0, "pose": {"pos": [*pos, 0.075], "yaw": 0.0}, "lidar": [6.0] * 8,
            "thermal": [[0.0]], "acoustic": {"bearing": 0.0, "level": 0.0},
            "motion": {"state": state, "target": target}}


def sim_log(outcome, reason, at=(1.0, 1.0)):
    return {"t": 1, "perception": f"responder at [{at[0]}, {at[1]}]", "model": "sim", "physics": "mujoco",
            "outcome": outcome, "reason": reason}


class World:
    """A hub Bus with the T12 router, the T13 loop, the handoff and a stand-in physics check."""

    def __init__(self, physics_ok=True):
        self.bus = Bus()
        self.sent = []
        for topic in ("scout/goto", "responder/action", "gate/request", "log/decision", "route/proposed"):
            self.bus.subscribe(topic, lambda d, t=topic: self.sent.append((t, d)))
        self.physics_ok = physics_ok

    async def start(self, start_cell=(2, 2, 0), occupied=()):
        self.router = RoutePlanner(self.bus)
        self.bus.subscribe("map/cells", self.router.update_map)
        self.bus.subscribe("map/hazards", self.router.update_hazards)
        self.loop = await L.start(self.bus, self.router, budget=False)
        self.handoff = H.start(self.bus, self.loop, self.router, responder_start=start_cell)

        async def verify(route):  # stand-in for sim's physics check (T05)
            await self.bus.publish("route/verified", {"id": route["id"], "ok": self.physics_ok,
                                                      "unstable_cells": [], "detail": "stand-in check"})

        self.bus.subscribe("route/proposed", verify)
        await self.bus.publish("map/cells", map_cells(occupied))
        await self.bus.publish("map/hazards", [])
        return self

    def topics(self, topic):
        return [d for t, d in self.sent if t == topic]

    def handoff_logs(self, outcome=None):
        return [d for d in self.topics("log/decision") if d["model"] == H.MODEL
                and (outcome is None or d["outcome"] == outcome)]


def run(coro):
    return asyncio.run(coro)


def test_confident_casualty_goes_straight_to_the_responder():
    async def go():
        w = await World().start()
        await w.bus.publish("map/casualties", [casualty(confidence=0.9)])
        return w

    w = run(go())
    actions = [a["action"] for a in w.topics("responder/action")]
    assert actions == ["move", "place_supply", "release"]
    assert w.topics("gate/request") == [], "no human gate on a confident casualty"
    assert w.handoff_logs("handoff") and w.handoff.active == "c1"
    route = w.topics("route/proposed")[0]
    assert route["cells"][0] == [2, 2, 0]
    gx, gy, _ = route["cells"][-1]
    assert ((gx + 0.5) * RES - 1.5) ** 2 + ((gy + 0.5) * RES - 1.5) ** 2 <= H.GOAL_RADIUS_M ** 2


def test_low_confidence_casualty_asks_a_human_and_does_not_move():
    async def go():
        w = await World().start()
        await w.bus.publish("map/casualties", [casualty(confidence=0.3)])
        return w

    w = run(go())
    assert len(w.topics("gate/request")) == 1
    assert w.topics("responder/action") == [], "nothing moves without the human"


def test_middle_confidence_sends_the_scout_to_re_look_first():
    async def go():
        w = await World().start()
        await w.bus.publish("map/casualties", [casualty(confidence=0.6)])
        return w

    w = run(go())
    assert w.topics("responder/action") == [] and w.topics("gate/request") == []
    assert w.topics("scout/goto"), "the T13 loop re-looks before acting"


def test_most_confident_casualty_first_then_the_next_with_another_supply():
    async def go():
        w = await World().start()
        await w.bus.publish("map/casualties", [casualty("c1", (1.5, 1.5, 0.1), 0.85),
                                               casualty("c2", (0.4, 1.6, 0.1), 0.95)])
        first = w.handoff.active
        await w.bus.publish("log/decision", sim_log("done", "placed water at [0.40, 1.50]", at=(0.4, 1.4)))
        return w, first

    w, first = run(go())
    assert first == "c2"
    assert w.handoff.served == {"c2"} and w.handoff.active == "c1"
    items = [a["item"] for a in w.topics("responder/action") if a["action"] == "place_supply"]
    assert items == ["water", "first_aid_kit"]
    assert w.handoff.responder_cell == (8, 28, 0), "next mission starts where the Responder stopped"


def test_responder_blocked_resplits_to_the_scout_and_retries_after_a_rescan():
    async def go():
        w = await World().start()
        await w.bus.publish("map/casualties", [casualty()])
        await w.bus.publish("log/decision", sim_log("blocked", "collision ray: block ahead on route r1, stopped"))
        after_block = [d for d in w.topics("scout/goto") if d["reason"].startswith("re-split")]
        assert w.handoff.active is None and w.handoff.waiting_scan
        await w.bus.publish("map/casualties", [casualty()])          # no retry before the re-scan
        assert w.handoff.active is None
        await w.bus.publish("map/cells", map_cells())                 # too soon: not a re-scan yet
        assert w.handoff.active is None
        w.handoff.blocked_at -= H.RETRY_AFTER_S                        # time passes
        await w.bus.publish("map/cells", map_cells())                 # the Scout re-scanned
        retried = w.handoff.active
        await w.bus.publish("log/decision", sim_log("blocked", "collision ray: block ahead on route r2, stopped"))
        return w, after_block, retried

    w, after_block, retried = run(go())
    assert after_block and after_block[0]["target"][:2] == [1.025, 1.025]
    assert retried == "c1" and w.handoff.attempts["c1"] == 2
    assert "c1" in w.handoff.skipped, "gives up after MAX_ATTEMPTS"
    assert w.handoff_logs("requeued") and w.handoff_logs("skipped")


def test_a_shift_freeze_does_not_use_up_a_try():
    """#52 E2E: the aftershock shift revokes the permit and freezes the Responder (T13 re-plans).
    That is the world changing, not the Responder failing, so it must not cost c1 a try: the first
    real collision-ray block after it is try 1 of MAX_ATTEMPTS, not the last one."""
    async def go():
        w = await World().start()
        await w.bus.publish("map/casualties", [casualty()])
        await w.bus.publish("log/decision", sim_log(
            "frozen", "move permit for r1 revoked (revoked: LiDAR hit inside the route at 1 cell(s)): "
                      "stopped, dropped 3 queued action(s)"))
        frozen_attempts = w.handoff.attempts["c1"]
        w.handoff.blocked_at -= H.RETRY_AFTER_S
        await w.bus.publish("map/cells", map_cells())                 # re-scanned: retry
        await w.bus.publish("log/decision", sim_log("blocked", "collision ray: block ahead on route r2, stopped"))
        return w, frozen_attempts

    w, frozen_attempts = run(go())
    assert frozen_attempts == 0, "the shift freeze gave the try back"
    assert w.handoff.attempts["c1"] == 1
    assert "c1" not in w.handoff.skipped, "one real block after a shift is not MAX_ATTEMPTS"
    assert len(w.handoff_logs("requeued")) == 2 and not w.handoff_logs("skipped")


def test_scout_blocked_is_left_to_the_explorer_and_noted_once():
    """No competing scout/goto (in a real-lane run one alternated with the Explorer every tick)."""
    async def go():
        w = await World().start()
        blocked = [2.0, 0.3]
        for _ in range(5):                       # the Scout reports blocked on every frame
            await w.bus.publish("sensors/scout", scout_frame((1.9, 0.3), "blocked", blocked))
        return w

    w = run(go())
    assert [d for d in w.topics("scout/goto") if d["reason"].startswith("re-split")] == []
    assert len(w.handoff_logs("resplit")) == 1


def test_scout_blocked_while_the_responder_keeps_its_casualty():
    async def go():
        w = await World().start()
        await w.bus.publish("map/casualties", [casualty()])
        await w.bus.publish("sensors/scout", scout_frame((1.9, 0.3), "blocked", [2.0, 0.3]))
        return w

    w = run(go())
    assert w.handoff.active == "c1"
    assert next(a["action"] for a in w.topics("responder/action")) == "move"


def test_no_free_cell_beside_the_casualty_sends_the_scout_to_look():
    async def go():
        w = await World().start()
        await w.bus.publish("map/casualties", [casualty(pos=(3.5, 3.5, 0.1))])   # outside the mapped room
        return w

    w = run(go())
    assert w.handoff.active is None and w.topics("responder/action") == []
    assert any(d["reason"].startswith("handoff: map a free cell") for d in w.topics("scout/goto"))


def test_planner_start_attaches_the_handoff():
    import planner

    async def go():
        bus = Bus()
        router = await planner.start(bus)
        router.task.cancel()
        await asyncio.gather(router.task, return_exceptions=True)
        return router

    router = run(go())
    assert isinstance(router.handoff, H.Handoff) and router.handoff.loop is router.loop


def test_starts_from_a_free_cell_when_the_responder_cell_looks_occupied():
    """The Scout's LiDAR can map the Responder's own body (or rubble beside it) as occupied."""
    async def go():
        w = await World().start(start_cell=(2, 2, 0), occupied={(2, 2), (2, 3), (3, 2)})
        await w.bus.publish("map/casualties", [casualty(confidence=0.9)])
        return w

    w = run(go())
    route = w.topics("route/proposed")[0]
    start = tuple(route["cells"][0])
    assert start != (2, 2, 0) and abs(start[0] - 2) * RES <= H.START_SNAP_M and abs(start[1] - 2) * RES <= H.START_SNAP_M
    assert [a["action"] for a in w.topics("responder/action")][:1] == ["move"]


def test_look_requests_are_rate_limited():
    async def go():
        w = await World().start()
        for _ in range(5):
            await w.bus.publish("map/casualties", [casualty(pos=(3.5, 3.5, 0.1))])
        return w

    w = run(go())
    assert len([d for d in w.topics("scout/goto") if d["reason"].startswith("handoff: map")]) == 1


def test_blocked_route_replans_from_where_the_responder_stopped():
    """ref BLOCKED-START: wired as the hub wires it (loop.start without start_cell), a blocked Responder
    was re-planned from its mission start every time, so it drove back into the same block forever."""
    async def go():
        w = await World().start(start_cell=(2, 2, 0))
        await w.bus.publish("map/casualties", [casualty(confidence=0.9)])
        first = w.topics("route/proposed")[0]
        await w.bus.publish("responder/pose", {"t": 5.0, "pos": [1.02, 1.02, 0.05], "yaw": 0.0,
                                               "state": "blocked", "route": first["id"], "carrying": ["water"]})
        n = len(w.topics("route/proposed"))
        await w.bus.publish("log/decision", sim_log(
            "blocked", f"collision ray: block ahead on route {first['id']}, stopped, dropped 2 queued action(s)",
            at=(1.02, 1.02)))
        await w.bus.publish("map/cells", map_cells())
        return first, w.topics("route/proposed")[n:]

    first, later = run(go())
    assert first["cells"][0] == [2, 2, 0]
    assert later, "a new route after the block"
    assert all(r["cells"][0] == [20, 20, 0] for r in later), [r["cells"][0] for r in later]
