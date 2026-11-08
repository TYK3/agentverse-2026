"""WALL-FLICKER: after an aftershock, rays grazing a standing wall must not clear its cells."""

from perception.grid import CLEAR_PASSES, Grid


def test_standing_neighbour_holds_wall_face_cell():
    g = Grid()
    for i in range(5):
        g.hit((i, 5, 1))
    g.begin_change(1.0)
    for i in (0, 1, 3, 4):
        g.hit((i, 5, 1))
    for _ in range(3 * CLEAR_PASSES):
        g.free((2, 5, 1))
    assert (2, 5, 1) not in g.cleared
    assert g.cells[(2, 5, 1)]["occupied"]


def test_moved_block_clears_and_stray_new_return_beside_it_does_not_hold_it():
    g = Grid()
    block = [(30, 30, 1), (31, 30, 1)]
    for c in block:
        g.hit(c)
    g.free((32, 30, 1))
    g.begin_change(1.0)
    g.hit((32, 30, 1))                 # free before the change, so a new return does not hold (31, 30, 1)
    for _ in range(CLEAR_PASSES):
        for c in block:
            g.free(c)
    assert all(c in g.cleared for c in block)
    assert g.column(30, 30) == ("seen", False)
