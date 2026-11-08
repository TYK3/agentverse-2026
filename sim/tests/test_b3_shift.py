"""B3-SHIFT: a slab shifts as the Scout reaches B2 on its way to B3. The Scout stops at once, refuses
to move while the shift settles, re-checks from fresh looks, then still reaches c3 in B3 without ever
driving into the slab (sim/levels.py shift_slab, sim/demo_descent.py run(shift_on="B2"))."""

import pytest

from sim import levels
from sim.demo_descent import DT, RECHECK_FRAMES, RES
from sim.levels import LEVEL_Z, RIDE, SETTLE, LevelWorld, max_jump

B1, B2, B3 = LEVEL_Z["B1"], LEVEL_Z["B2"], LEVEL_Z["B3"]
SLAB_LO, SLAB_HI = (4.45, 1.05), (5.0, 1.35)       # landed footprint, sim/scenes/make_levels.py
TO_B2 = [(1.2, 2.1, 0.6), (3.8, 2.1, 0.0), (3.8, 0.3, 0.0), (1.3, 0.3, B1),
         (1.35, 1.5, B1), (2.3, 2.1, B1), (4.75, 2.1, B2), (4.75, 1.6, B2)]
DETOUR = [(4.2, 1.55, B2), (4.2, 0.85, B2), (4.75, 0.85, B2), (4.75, 0.3, B2), (2.0, 0.3, B3)]


def on_slab(x, y, pad=0.0):
    return SLAB_LO[0] - pad <= x <= SLAB_HI[0] + pad and SLAB_LO[1] - pad <= y <= SLAB_HI[1] + pad


def slab_cell(c):
    """A B2-level map cell [i, j, k] whose centre is on the slab's footprint."""
    return on_slab((c[0] + 0.5) * RES, (c[1] + 0.5) * RES) and abs(c[2] * RES - B2) <= 0.2


def drive(w, target, max_ticks=600):
    w.goto({"target": list(target), "reason": "test"})
    for _ in range(max_ticks):
        w.tick(DT)
        if w.state != "moving":
            break
    return w.state


@pytest.fixture(scope="module")
def shifted():
    from sim.demo_descent import run
    return run(max_t=500.0, floor="B3", shift_on="B2")


def test_slab_is_out_of_reach_until_it_shifts():
    w = LevelWorld(render=False)
    probe = ((SLAB_LO[0] + SLAB_HI[0]) / 2, (SLAB_LO[1] + SLAB_HI[1]) / 2)
    assert w._floor_at(probe, B1 - 0.1) == pytest.approx(B2)             # plain B2 floor
    assert w.shift_slab() is True
    assert w._floor_at(probe, B1 - 0.1) == pytest.approx(B2 + 0.12)      # now the slab's top
    assert w.shift_slab() is False                                      # it shifts once
    assert ("world/change", {"kind": "aftershock", "t": 0.0, "moved_blocks": ["shift_slab"]}) in w.tick(DT)


def test_shift_stops_the_scout_and_refuses_goto_while_it_settles():
    w = LevelWorld(render=False)
    for leg in TO_B2[:7]:
        assert drive(w, leg) == "arrived"
    w.goto({"target": [4.75, 0.6, B2], "reason": "test"})              # the direct way to R4
    w.tick(DT)
    assert w.state == "moving"
    w.shift_slab()
    assert (w.state, w.target) == ("blocked", None)
    still = w.pos.copy()
    for _ in range(round(SETTLE / DT) - 1):
        w.goto({"target": [4.75, 0.6, B2], "reason": "test"})
        w.tick(DT)
        assert w.state == "blocked" and w.pos == pytest.approx(still)  # nothing moves on the old map
    w.tick(DT)
    assert not w.settling()


def test_after_the_shift_the_direct_way_is_refused_and_the_detour_reaches_b3():
    w = LevelWorld(render=False)
    for leg in TO_B2:
        assert drive(w, leg) == "arrived"
    w.shift_slab()
    for _ in range(round(SETTLE / DT)):
        w.tick(DT)
    assert drive(w, (4.75, 0.6, B2)) == "blocked"                       # the slab is in the way
    assert not on_slab(*w.pos[:2])
    for leg in DETOUR:
        assert drive(w, leg) == "arrived", (leg, w.pos.tolist())
    assert w.level() == "B3"
    assert max_jump(w.trace) < 0.035


def test_closed_loop_with_a_slab_shift_still_reaches_b3(shifted):
    assert shifted["reached"], shifted["log"][-5:]
    assert shifted["levels"] == ["L1", "ground", "B1", "B2", "B3"]
    assert shifted["max_jump"] < 0.035
    assert shifted["final_pos"][2] == pytest.approx(B3 + RIDE)
    assert shifted["world_change"] == [{"kind": "aftershock", "t": shifted["shift"]["t"],
                                        "moved_blocks": ["shift_slab"]}]


def test_the_scout_stopped_on_b2_and_stayed_put_through_the_recheck(shifted):
    s = shifted["shift"]
    assert s["state"] == "blocked"
    assert s["pos"][2] - RIDE == pytest.approx(B2, abs=0.005)           # shifted once it stood on B2
    assert len(s["held"]) >= round(SETTLE / DT) - 1 + RECHECK_FRAMES
    assert len(set(s["held"])) == 1 and s["held"][0] == pytest.approx(s["pos"])
    assert s["forgot"] > 0                                               # the stale floor map was dropped


def test_every_plan_after_the_recheck_avoids_the_slab_and_the_scout_never_enters_it(shifted):
    s = shifted["shift"]
    assert s["plans"]
    for cells in s["plans"]:
        assert not any(slab_cell(c) for c in cells)
    after = [(x, y) for t, x, y, z in shifted["trace"] if t > s["t"] and abs(z - RIDE - B2) < 0.05]
    assert after and not any(on_slab(x, y, pad=0.05) for x, y in after)


def test_the_slab_is_in_the_map_from_fresh_looks(shifted):
    occupied = [c["cell"] for c in shifted["map"]["cells"] if c["occupied"] and slab_cell(c["cell"])]
    assert len(occupied) >= 10
    assert shifted["responder_route"] == "ok" and shifted["route_k"] == (12, -36)


def test_without_a_shift_the_slab_stays_parked():
    w = LevelWorld(render=False)
    g = w.m.geom(levels.SHIFT_GEOM).id
    assert w.m.geom_pos[g][2] < B3 - 1.0
    assert w.shifted_at is None and not w.settling()
