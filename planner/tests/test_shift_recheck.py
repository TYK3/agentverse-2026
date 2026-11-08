"""G4 races: old work cannot restore a route after the world it checked has changed."""

import asyncio

import pytest

from planner.shift_recheck import ShiftRecheck


def route(rid="r1"):
    return {"id": rid, "cells": [[x, 0, 0] for x in (2, 3, 4)]}


def approve(guard, token):
    assert guard.verified(token, {"id": token.route, "ok": True})
    assert guard.permitted(token, {"route": token.route, "granted": True})


def frame(t, distance=.35):
    return {"t": t, "pose": {"pos": [.025, .025, .075]}, "lidar": [distance] + [6.] * 7}


def shifted():
    guard = ShiftRecheck()
    guard.on_world_change({"t": 10, "kind": "aftershock", "moved_blocks": ["b7"]})
    token = guard.begin(route())
    approve(guard, token)
    return guard, token


def test_offline_initial_check_needs_physics_and_permit_but_no_model_receipt():
    guard = ShiftRecheck()
    token = guard.begin(route())
    assert not guard.decision(token).ready
    guard.verified(token, {"id": "r1", "ok": True})
    assert not guard.decision(token).ready
    guard.permitted(token, {"route": "r1", "granted": True})
    assert guard.decision(token).ready


@pytest.mark.parametrize("kind", ["aftershock", "block_added"])
def test_shift_invalidates_captured_physics_permit_and_model_completions(kind):
    guard = ShiftRecheck()
    old = guard.begin(route())
    approve(guard, old)
    assert guard.decision(old).ready
    guard.on_world_change({"t": 10, "kind": kind, "moved_blocks": ["b7"]})
    current = guard.begin(route())  # even reuse of the same route id cannot reuse the old check
    assert not guard.verified(old, {"id": "r1", "ok": True})
    assert not guard.permitted(old, {"route": "r1", "granted": True})
    assert not guard.reviewed(old, {"id": "gem-old", "route": "r1", "mode": "live"})
    guard.observe(frame(11))
    assert not guard.decision(old).ready
    assert not guard.decision(current).ready
    approve(guard, current)
    assert guard.decision(current).ready


@pytest.mark.parametrize("mode", ["live", "replay", "off"])
def test_clear_review_and_old_map_timestamp_cannot_substitute_for_fresh_measurements(mode):
    guard, token = shifted()
    assert guard.reviewed(token, {"id": "gem-review", "route": "r1", "mode": mode,
                                  "verdict": "clear", "approved": True})
    assert not guard.observe(frame(9))
    assert not guard.observe(frame(10))
    decision = guard.decision(token)
    assert not decision.ready and decision.missing == ((2, 0), (3, 0), (4, 0))
    assert guard.observe(frame(11))
    assert guard.decision(token).ready


def test_every_route_cell_needs_a_post_change_measured_free_prefix():
    guard, token = shifted()
    for n, x in enumerate((2, 3, 4), 11):
        # A north-going measured ray crosses just one of the three route columns.
        guard.observe({"t": n, "pose": {"pos": [(x+.5)*.05, -.125, .075]},
                       "lidar": [6., .3, 6., 6.]})
        assert guard.decision(token).ready is (x == 4)


@pytest.mark.parametrize("distance", [6., 100., 0., -1., float("nan"), float("inf"), True])
def test_misses_and_invalid_ranges_are_not_fresh_free_space(distance):
    guard, token = shifted()
    guard.observe(frame(11, distance))
    assert not guard.decision(token).ready


def test_new_hit_invalidates_the_check_even_after_it_was_ready():
    guard, token = shifted()
    guard.observe(frame(11))
    assert guard.decision(token).ready
    guard.observe(frame(12, .15))  # return inside route column 3
    assert not guard.decision(token).ready
    assert not guard.verified(token, {"id": "r1", "ok": True})
    assert not guard.permitted(token, {"route": "r1", "granted": True})
    guard.observe(frame(13))
    assert not guard.decision(token).ready, "a free ray cannot resurrect the invalidated work"
    new = guard.begin(route("r2"))
    approve(guard, new)
    assert guard.decision(new).ready


def test_duplicate_and_reordered_frames_do_not_replace_newer_observations():
    guard, token = shifted()
    guard.observe(frame(12))
    assert not guard.observe(frame(11, .15))
    assert not guard.observe(frame(12, .15))
    assert guard.decision(token).ready


def test_late_change_notification_cannot_relabel_a_received_frame_as_fresh():
    guard, old = shifted()
    guard.observe(frame(12))
    assert guard.decision(old).ready
    guard.on_world_change({"t": 11})
    new = guard.begin(route("r2"))
    approve(guard, new)
    assert not guard.observe(frame(12))
    assert not guard.decision(new).ready
    guard.observe(frame(13))
    assert guard.decision(new).ready


def test_replacing_a_check_freezes_geometry_and_discards_old_answers():
    guard = ShiftRecheck()
    data = route()
    old = guard.begin(data)
    data["cells"].clear()
    approve(guard, old)
    assert guard.decision(old).ready
    new = guard.begin(route())
    assert new != old
    assert not guard.permitted(old, {"route": "r1", "granted": True})
    assert not guard.decision(new).ready


@pytest.mark.parametrize("field,payload", [
    ("verified", {"id": "other", "ok": True}),
    ("verified", {"id": "r1", "ok": 1}),
    ("permitted", {"route": "other", "granted": True}),
    ("permitted", {"route": "r1", "granted": "true"}),
])
def test_unrelated_or_nonliteral_positive_results_do_not_unlock(field, payload):
    guard = ShiftRecheck()
    token = guard.begin(route())
    assert not getattr(guard, field)(token, payload)
    assert not guard.decision(token).ready


@pytest.mark.parametrize("cells", [[], [[1, 2, -1]], [[1, 2, True]], [[1., 2, 0]]])
def test_unsupported_routes_are_rejected_without_flattening(cells):
    with pytest.raises(ValueError):
        ShiftRecheck().begin({"id": "r1", "cells": cells})


def test_completions_awaiting_the_network_keep_their_original_generation():
    async def scenario():
        guard = ShiftRecheck()
        old = guard.begin(route())
        release = asyncio.Event()

        async def delayed():
            await release.wait()
            return (guard.verified(old, {"id": "r1", "ok": True}),
                    guard.permitted(old, {"route": "r1", "granted": True}),
                    guard.reviewed(old, {"id": "gem-delayed", "route": "r1"}))

        pending = asyncio.create_task(delayed())
        await asyncio.sleep(0)
        guard.on_world_change({"t": 10})
        current = guard.begin(route())
        guard.observe(frame(11))
        release.set()
        assert await pending == (False, False, False)
        assert not guard.decision(current).ready
        approve(guard, current)
        assert guard.decision(current).ready

    asyncio.run(scenario())


@pytest.mark.parametrize("t", [True, -1, float("nan"), float("inf"), 10**400])
def test_unusable_change_chronology_invalidates_permission_before_rejecting(t):
    guard = ShiftRecheck()
    old = guard.begin(route())
    approve(guard, old)
    with pytest.raises(ValueError):
        guard.on_world_change({"t": t})
    assert not guard.decision(old).ready
