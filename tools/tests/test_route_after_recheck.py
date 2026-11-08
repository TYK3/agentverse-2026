"""A new route on a live B2 run is issued only after the post-shift recheck.

Recheck record: ``mapped``. ``tools/run_b2.py`` writes it once the Scout's own
measurements occupy cells in the shifted slab's footprint (LiDAR, or a refused
step). That is the post-shift recheck on this log. CONTRACT.md re-earns a move
permit only with ``permit/route`` evidence kind ``fresh_scan``; this runner does
not log permits, and a ``plan`` has no recheck flag (``why`` is ``route``,
``explore`` or ``probe``).

New route: a ``plan`` whose cells are not the route in force when the slab
dropped (the same cell list, or the remainder of it still ahead), or whose
floor index ``k`` resets by climbing above that route's highest ``k``.
"""

import json

import pytest

pytest.importorskip("mujoco")

RECHECK_KIND = "mapped"
NEW_ROUTE_KIND = "plan"


def _cells(record):
    return [tuple(cell) for cell in record.get("cells") or []]


def _same_route(cells, driven):
    """True when ``cells`` is the driven route, or the part of it still ahead."""
    if not cells or not driven:
        return False
    if cells == driven:
        return True
    return len(cells) <= len(driven) and driven[-len(cells):] == cells


def _route_k_resets(cells, driven):
    """True when this plan's highest floor index climbs back above the driven route.

    ``route_k`` elsewhere is ``(max k, min k)`` of a route's cells. A continuation
    stays at or below the driven route's highest ``k``.
    """
    if not cells or not driven:
        return False
    return max(cell[2] for cell in cells) > max(cell[2] for cell in driven)


def _is_new_route(record, driven):
    if record.get("kind") != NEW_ROUTE_KIND:
        return False
    cells = _cells(record)
    if not cells:
        return False
    return (not _same_route(cells, driven)) or _route_k_resets(cells, driven)


@pytest.mark.slow
def test_new_route_is_issued_only_after_the_post_shift_recheck(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_MODE", "off")
    from tools.run_b2 import run

    _, path = run(seed=0, out_dir=tmp_path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    shift_at = next(i for i, row in enumerate(rows) if row["kind"] == "shift")
    driven_at = next(
        i for i in range(shift_at - 1, -1, -1)
        if rows[i]["kind"] == NEW_ROUTE_KIND and rows[i].get("why") == "route" and rows[i].get("cells")
    )
    driven = _cells(rows[driven_at])
    core = {tuple(cell) for cell in rows[shift_at]["core"]}
    assert {cell[:2] for cell in driven} & core, (
        f"plan {driven_at} is not the route the shift at record {shift_at} landed on"
    )

    rechecks = [i for i, row in enumerate(rows) if i > shift_at and row["kind"] == RECHECK_KIND]
    new_routes = [i for i, row in enumerate(rows) if i > shift_at and _is_new_route(row, driven)]
    assert rechecks, (
        f"shift record {shift_at} at t={rows[shift_at]['t']} has no {RECHECK_KIND} recheck after it"
    )
    first_recheck = rechecks[0]
    between = [i for i in new_routes if shift_at < i < first_recheck]
    assert between == [], (
        f"new route record(s) {between} sit between shift {shift_at} "
        f"(t={rows[shift_at]['t']}) and {RECHECK_KIND} recheck {first_recheck} "
        f"(t={rows[first_recheck]['t']})"
    )
    assert new_routes, (
        f"shift record {shift_at} at t={rows[shift_at]['t']} is not followed by a new route"
    )
    first_route = new_routes[0]
    issued = _cells(rows[first_route])
    assert first_route > first_recheck, (
        f"first post-shift route is record {first_route} at t={rows[first_route]['t']} "
        f"({len(issued)} cells, driven route was record {driven_at} with {len(driven)} cells) "
        f"and is not preceded by {RECHECK_KIND} recheck {first_recheck} "
        f"at t={rows[first_recheck]['t']}"
    )
    assert issued != driven
    assert rows[first_recheck]["kind"] == RECHECK_KIND
    assert rows[first_route]["kind"] == NEW_ROUTE_KIND
