"""WALL-FLICKER: after an aftershock, rays grazing a wall that still stands must not clear its cells.

Before the fix, a wall-face cell with no return since the change was cleared (set free) by
CLEAR_PASSES = 3 grazing passes, then set occupied again by the next return: 258 wall cells flipped
free and back in a real run. Now a cell is not cleared while a side neighbour is still occupied and
still returning hits, and only once its passes since the change outnumber its hits before it."""

from perception.grid import CLEAR_PASSES, Grid
from perception.tests.test_grid import HALF, Z, sweep, wall_cells


def wall(g, n_hits=5, row=5, length=10):
    cells = [(i, row, 1) for i in range(length)]
    for c in cells:
        for _ in range(n_hits):
            g.hit(c)
    return cells


def test_grazing_passes_along_a_standing_wall_do_not_clear_it():
    g = Grid()
    cells = wall(g)
    face = (4, 5, 1)
    g.begin_change(1.0)
    for c in cells:
        if c != face:
            g.hit(c)                   # the rest of the wall still returns; the face cell gets none

    for _ in range(3 * CLEAR_PASSES):
        g.free(face)                   # grazing rays pass through the face cell, no return there
    assert face not in g.cleared
    assert g.cells[face]["occupied"], "the wall cell stays occupied"


def test_a_still_occupied_neighbour_holds_a_cell_even_with_few_old_hits():
    g = Grid()
    cells = wall(g, n_hits=1)
    g.begin_change(1.0)
    for c in cells:
        if c != (4, 5, 1):
            g.hit(c)
    for _ in range(CLEAR_PASSES + 2):
        g.free((4, 5, 1))
    assert (4, 5, 1) not in g.cleared


def test_passes_must_outnumber_the_hits_before_the_change():
    g = Grid()
    c = (20, 20, 1)
    for _ in range(6):
        g.hit(c)                       # a lone block, seen 6 times
    g.begin_change(1.0)
    for _ in range(CLEAR_PASSES):
        g.free(c)
    assert c not in g.cleared, "3 passes do not outweigh 6 returns"
    for _ in range(4):
        g.free(c)                      # 7 passes > 6 hits
    assert c in g.cleared
    assert g.column(20, 20) == ("seen", False)


def test_a_block_that_moved_away_still_clears_as_a_whole():
    # Two adjacent cells of one block: neither returns after the change, so neither holds the other.
    g = Grid()
    block = [(30, 30, 1), (31, 30, 1)]
    for c in block:
        g.hit(c)
        g.hit(c)
    g.begin_change(1.0)
    for _ in range(CLEAR_PASSES):
        for c in block:
            g.free(c)
    assert all(c in g.cleared for c in block)


def test_room_walls_survive_grazing_sweeps_after_a_change():
    # Guard on real sweeps (passes on main too: the synthetic room's exact rays never graze a face
    # cell without a return; the real flicker needs the sim's noisy ranges).
    g = Grid()
    spots = [(0.0, 0.0), (0.6, 0.4), (-0.7, -0.5), (0.0, 0.9)]
    for pos in spots:
        g.add_scan((*pos, Z), sweep(pos))
    walls = set(wall_cells())
    g.begin_change(5.0)
    # After the shake the Scout drives close along each wall: its rays meet the walls at shallow angles.
    near = HALF - 0.08
    for pos in [(near, -0.6), (near, 0.0), (near, 0.6), (-near, 0.3), (0.3, near), (-0.3, -near)]:
        for _ in range(3):
            g.add_scan((*pos, Z), sweep(pos))
    flipped = sorted(c for c in walls if c in g.cleared)
    assert flipped == [], f"{len(flipped)} standing wall cells cleared, e.g. {flipped[:5]}"
    assert all(g.cells[c]["occupied"] for c in walls if c in g.cells)

