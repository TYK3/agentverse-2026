"""STALE-RECHECK-FIX: after a world change, predicted at-risk cells are forgotten until re-scanned,
and snapshots do not re-stamp un-rescanned cells from before the change as freshly seen."""

from perception.grid import Grid
from perception.hazards import Hazards

CHANGE = {"kind": "aftershock", "t": 5.0, "moved_blocks": ["b7"]}
K = 1


def seen_room():
    g = Grid()
    for i in range(20):
        for j in range(20):
            g.free((i, j, K))
    g.t = 5.0
    return g


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
    # Forgotten cells go out as unknown in the next delta so the planner drops them until re-scanned.
    delta = {tuple(r["cell"][:2]): r["state"] for r in g.delta(5.0)["cells"]}
    assert all(delta.get(ij) == "unknown" for ij in risky)


def test_change_preserves_before_state_for_scan_diff_on_forgotten_cells():
    g = seen_room()
    g.hit((9, 10, K))                                       # occupied cell in the at-risk ring
    h = Hazards(g)
    h.collapsed[(10, 10)] = "debris seen landing earlier"
    h.update(5.0)
    h.on_change(CHANGE, t=5.0)
    assert g.state((9, 10, K)) == "unknown"
    assert g.before[(9, 10, K)] is True                     # frozen before forget(), so scan diff still works
    for _ in range(3):
        g.free((9, 10, K))
    assert (9, 10, K) in g.cleared


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
    assert [r["cell"] for r in snap["cells"] if r["state"] == "seen"] == [[0, 0, 0]]
