"""LOOP-RELOOK-S4: while planner/permit.py has the Scout re-scanning a revoked route, the loop's
"no verified route yet" goal re-look must not pull the Scout away from it."""

import asyncio

from planner import loop as L
from planner.tests.test_loop import setup, two_gap_map

GAPS = {(4, 1), (4, 5)}  # both wall gaps unknown: no route over seen cells
PERMIT_GOTO = {"target": [0.45, 0.15, 0.075], "reason": "re-look to re-earn move permission on route r1"}


def goal_relooks(bus):
    return [d for d in bus.of("scout/goto") if d["reason"].endswith("no verified route yet")]


def rescan(bus, clock, dt):
    clock.now += dt
    asyncio.run(bus.publish("map/cells", two_gap_map(GAPS)))


def test_goal_relook_held_while_permit_relook_pending():
    bus, lp, clock = setup(unknown=GAPS)
    lp.last_route = "r1"  # r1 was proposed, then its permit was revoked
    assert len(goal_relooks(bus)) == 1
    asyncio.run(bus.publish("scout/goto", PERMIT_GOTO))
    rescan(bus, clock, 2.0)
    assert len(goal_relooks(bus)) == 1, "goal re-look overrode the permit re-look"
    assert any("re-scans revoked route r1" in d["reason"] for d in bus.of("log/decision"))
    rescan(bus, clock, L.RELOOK_EVERY_S)  # permit.py went quiet: the goal re-look comes back
    assert len(goal_relooks(bus)) == 2


def test_permit_regrant_releases_the_hold():
    bus, lp, clock = setup(unknown=GAPS)
    lp.last_route = "r1"  # r1 was proposed, then its permit was revoked
    asyncio.run(bus.publish("scout/goto", PERMIT_GOTO))
    asyncio.run(bus.publish("permit/route", {"route": "r1", "granted": True, "t": 1.0, "reason": "re-earned",
                                             "evidence": []}))
    rescan(bus, clock, 2.0)
    assert len(goal_relooks(bus)) == 2


def test_other_scout_gotos_do_not_hold():
    bus, lp, clock = setup(unknown=GAPS)
    lp.last_route = "r1"  # r1 was proposed, then its permit was revoked
    asyncio.run(bus.publish("scout/goto", {"target": [0.45, 0.15, 0.075], "reason": "frontier at cell [4, 1, 0]"}))
    rescan(bus, clock, 2.0)
    assert len(goal_relooks(bus)) == 2


def test_stale_route_relook_does_not_hold():
    bus, lp, clock = setup(unknown=GAPS)
    lp.last_route = "r2"  # r1 was replaced; permit.py still re-looks it
    asyncio.run(bus.publish("scout/goto", PERMIT_GOTO))
    rescan(bus, clock, 2.0)
    assert len(goal_relooks(bus)) == 2
