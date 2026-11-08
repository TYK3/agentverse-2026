"""RECHECK-FRESH: after a stop and recheck (slab shift / aftershock), the next plan must rest on a
fresh scan, not on data from before the change.

Three checks, each on the lane's own code with plain fakes (no sim, no sleeps):
1. planner: after world/change at t=30, a map/cells stamped t=10 (older than the change) must not
   trigger a re-plan; a map stamped after the change does.
2. perception: when the change is felt, cells in the columns predicted at risk are made unknown
   (Grid.forget), so they count only once the Scout has measured them again.
3. perception: a full map snapshot after the change must not pass off a cell last measured before
   the change as freshly seen (state "seen", stamped t=now, with no older per-cell time).

On main all three fail, so they are strict xfails: fixing the product turns them into XPASS
failures, and then the marks come off.
"""

import asyncio

import pytest

from perception.grid import Grid
from perception.hazards import Hazards
from planner import loop as L
from planner.tests.test_loop import setup, two_gap_map, verify

REASON = ("stale recheck on main: planner/loop.py on_map re-plans on any map/cells after world/change, "
          "even one stamped before the change (it counts messages, never compares t); "
          "perception/grid.py Grid.forget is never called, so cells around moved blocks stay seen; "
          "perception/__init__.py's 5 s full snapshot re-stamps cells last seen before the change with t=now")
stale = pytest.mark.xfail(strict=True, reason=REASON)

CHANGE = {"kind": "aftershock", "t": 30, "moved_blocks": ["b7"]}
K = 1


@stale
def test_planner_waits_for_a_map_newer_than_the_change():
    bus, lp, clock = setup()
    verify(bus, "r1", True)
    assert lp.state == L.EXECUTING
    asyncio.run(bus.publish("world/change", CHANGE))
    n = len(bus.of("route/proposed"))
    clock.now = 2.0
    old = dict(two_gap_map(), t=10)                      # measured before the change at t=30
    asyncio.run(bus.publish("map/cells", old))
    assert bus.of("route/proposed")[n:] == [], "re-planned on a map older than the change"
    assert lp.waiting_scan
    clock.now = 4.0
    asyncio.run(bus.publish("map/cells", dict(two_gap_map(), t=31)))
    new = bus.of("route/proposed")[n:]
    assert len(new) == 1 and new[0]["id"] != "r1"


def seen_room():
    g = Grid()
    for i in range(20):
        for j in range(20):
            g.free((i, j, K))
    g.t = 5.0
    return g


@stale
def test_change_forgets_cells_predicted_at_risk():
    g = seen_room()
    h = Hazards(g)
    h.collapsed[(10, 10)] = "debris seen landing earlier"   # its NEAR ring is at_risk
    h.update(5.0)
    risky = {ij for ij, (s, _) in h.labels.items() if s == "at_risk"}
    assert risky
    h.on_change(CHANGE, t=5.0)
    still_seen = sorted(ij for ij in risky if g.state((*ij, K)) == "seen")
    assert still_seen == [], f"{len(still_seen)} at-risk cells still 'seen' from before the change"


@stale
def test_snapshot_after_change_does_not_restamp_old_cells():
    g = seen_room()
    Hazards(g).on_change(CHANGE, t=5.0)
    g.free((0, 0, K))                                       # one cell measured again after the change
    g.t = 10.0
    snap = g.snapshot(10.0)
    stale_cells = [r["cell"] for r in snap["cells"]
                   if r["state"] == "seen" and r["cell"][:2] != [0, 0]
                   and r.get("seen_t", snap["t"]) >= 5.0]
    assert stale_cells == [], f"{len(stale_cells)} cells from before the change shown as seen at t=10"
