"""L1 checks: move permits are revoked by sensed change and re-earned only by fresh observation."""

import asyncio

from planner import permit

RES = permit.RES
# Route along y = 0.525 from x = 0.525 to 1.475 (cells i 10..29, j 10).
ROUTE = [[i, 10, 0] for i in range(10, 30)]
SCOUT = [0.025, 0.525, 0.075]


def sweep(hit_at=None, n=360):
    """A LiDAR sweep from SCOUT with no returns, or one return straight along +x at `hit_at` m."""
    ranges = [6.0] * n
    if hit_at is not None:
        ranges[0] = ranges[1] = ranges[-1] = hit_at  # three rays near +x hit the same spot
    return {"pose": {"pos": SCOUT, "yaw": 0.0}, "lidar": ranges}


def verified_permits(ok=True):
    ps = permit.Permits()
    ps.on_route_proposed({"id": "r1", "robot": "responder", "cells": ROUTE, "goal": "water", "model": "x"})
    out = ps.on_route_verified({"id": "r1", "ok": ok, "unstable_cells": [], "detail": ""}, 1.0)
    return ps, out


def topics(out):
    return [t for t, _ in out]


def test_walk_and_trace():
    cells = permit.walk(0.025, 0.025, 0.0, 0.2)
    assert cells == [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)]
    hits, free = permit.trace(0.025, 0.525, [1.0] + [6.0] * 359)
    assert hits == {(20, 10): 1}
    assert (19, 10) in free and (0, 10) in free


def test_verified_route_is_granted_with_evidence():
    _, out = verified_permits()
    assert topics(out) == ["permit/route", "log/decision"]
    msg = out[0][1]
    assert msg["granted"] is True and msg["route"] == "r1"
    assert [e["kind"] for e in msg["evidence"]] == ["verified", "clear"]
    assert out[1][1]["outcome"] == "permit granted"


def test_failed_physics_is_never_granted():
    ps, out = verified_permits(ok=False)
    assert out[0][1]["granted"] is False
    assert ps.on_sensors(sweep(), 2.0) == []  # a clear scan cannot grant an unverified route


def test_lidar_hit_inside_the_route_revokes_and_sends_a_relook():
    ps, _ = verified_permits()
    out = ps.on_sensors(sweep(hit_at=1.0), 2.0)
    assert topics(out) == ["permit/route", "log/decision", "scout/goto"]
    msg = out[0][1]
    assert msg["granted"] is False and msg["evidence"][-1]["kind"] == "shift"
    assert "re-earn" in out[2][1]["reason"]
    assert out[2][1]["target"][:2] == [round(20.5 * RES, 3), round(10.5 * RES, 3)]
    assert not ps.granted("r1")


def test_a_single_noisy_return_is_not_a_shift():
    ps, _ = verified_permits()
    one = sweep()
    one["lidar"][0] = 1.0
    assert ps.on_sensors(one, 2.0) == []
    assert ps.granted("r1")


def test_time_alone_never_re_earns_the_permit():
    ps, _ = verified_permits()
    ps.on_sensors(sweep(hit_at=1.0), 2.0)
    for t in range(3, 300):  # still blocked: the rubble is still in the scan
        assert ps.on_sensors(sweep(hit_at=1.0), float(t)) == [] or not ps.granted("r1")
    assert not ps.granted("r1")
    assert ps.on_hazards([], 400.0) == []  # nor does a quiet hazard update


def test_fresh_scan_of_every_route_cell_re_earns_it():
    ps, _ = verified_permits()
    ps.on_sensors(sweep(hit_at=1.0), 2.0)
    out = ps.on_sensors(sweep(), 5.0)  # the rubble is gone and every route cell is seen free
    assert topics(out) == ["permit/route", "log/decision"]
    msg = out[0][1]
    assert msg["granted"] is True and msg["evidence"][-1]["kind"] == "fresh_scan"
    assert "after the change at 2.0s" in msg["evidence"][-1]["detail"]


def test_partial_scan_is_not_enough():
    ps, _ = verified_permits()
    ps.on_sensors(sweep(hit_at=1.0), 2.0)
    short = sweep()
    short["lidar"][0] = short["lidar"][1] = short["lidar"][-1] = 0.6  # sees only part of the route
    ps.on_sensors(short, 3.0)
    assert not ps.granted("r1")


def test_sensed_hazard_revokes_and_must_clear_before_a_scan_counts():
    ps, _ = verified_permits()
    hz = [{"cell": [15, 10, 0], "status": "at_risk", "why": "slab moved 3 cm", "estimate": True}]
    out = ps.on_hazards(hz, 2.0)
    assert out[0][1]["granted"] is False and out[0][1]["evidence"][-1]["kind"] == "hazard"
    assert ps.on_sensors(sweep(), 3.0) == []  # hazard still reported: a clear scan is not enough
    assert ps.on_hazards([], 4.0) == []        # hazard gone, but no fresh look since
    out = ps.on_sensors(sweep(), 5.0)
    assert out[0][1]["granted"] is True


def test_l5_exclusion_counts_as_a_hazard():
    ps, _ = verified_permits()
    out = ps.on_hazards([{"cell": [12, 10, 0], "status": "stable", "why": "slab motion", "estimate": True,
                          "exclusion": True}], 2.0)
    assert out[0][1]["granted"] is False


def test_start_publishes_only_contract_topics():
    class Bus:
        def __init__(self):
            self.subs, self.sent = {}, []

        def subscribe(self, topic, fn):
            self.subs.setdefault(topic, []).append(fn)

        async def publish(self, topic, data):
            self.sent.append(topic)

        async def fire(self, topic, data):
            for fn in self.subs.get(topic, []):
                r = fn(data)
                if asyncio.iscoroutine(r):
                    await r

    async def run():
        bus = Bus()
        permit.start(bus, clock=lambda: 1.0)
        await bus.fire("route/proposed", {"id": "r1", "robot": "responder", "cells": ROUTE, "goal": "g",
                                          "model": "x"})
        await bus.fire("route/verified", {"id": "r1", "ok": True, "unstable_cells": [], "detail": ""})
        return bus

    bus = asyncio.run(run())
    from coord import messages

    want = ["permit/route", "log/decision"] if "permit/route" in messages.TOPICS else ["log/decision"]
    assert bus.sent == want
