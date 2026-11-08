"""STALE-OCCLUDED (ref #31/#144): after a change, a newly sensed obstacle hides what is behind it. Cells there
were seen free before the change, but no ray reaches them now, so the map must not keep calling them free:
they go back to unknown until a ray passes through them again. Scan diff only, never sim truth."""

import math

from perception.grid import SHADOW, Grid, cell_of

HALF = 1.02                     # room walls at x, y = +-1.02 m
Z = 0.075
BOX = ((0.30, -0.12), (0.42, 0.12))   # debris that lands after the change: x and y extents


def ray_to_box(pos, dx, dy):
    """Range along (dx, dy) from pos to the box, or inf."""
    (x0, y0), (x1, y1) = BOX
    lo, hi = -math.inf, math.inf
    for p, d, a, b in ((pos[0], dx, x0, x1), (pos[1], dy, y0, y1)):
        if abs(d) < 1e-12:
            if not a <= p <= b:
                return math.inf
            continue
        t0, t1 = sorted(((a - p) / d, (b - p) / d))
        lo, hi = max(lo, t0), min(hi, t1)
    return lo if 0 <= lo <= hi else math.inf


def sweep(pos, box=False, n=360):
    out = []
    for k in range(n):
        a = 2 * math.pi * k / n
        dx, dy = math.cos(a), math.sin(a)
        tx = (math.copysign(HALF, dx) - pos[0]) / dx if abs(dx) > 1e-9 else math.inf
        ty = (math.copysign(HALF, dy) - pos[1]) / dy if abs(dy) > 1e-9 else math.inf
        r = min(tx, ty)
        out.append(min(r, ray_to_box(pos, dx, dy)) if box else r)
    return out


def mapped_room():
    g = Grid()
    for _ in range(3):
        g.add_scan((0.0, 0.0, Z), sweep((0.0, 0.0, Z)))
    return g


def behind(r):
    """The cell straight behind the box on the +x ray, r metres from the scanner."""
    return cell_of((r, 0.0, Z))


def test_cells_hidden_behind_new_debris_become_unknown():
    g = mapped_room()
    assert g.state(behind(0.6)) == "seen" and not g.cells[behind(0.6)]["occupied"]
    g.begin_change(5.0)
    for _ in range(2):                                     # APPEAR_HITS sweeps make the box `appeared`
        g.add_scan((0.0, 0.0, Z), sweep((0.0, 0.0, Z), box=True))
    assert cell_of((0.30, 0.0, Z)) in g.appeared
    for r in (0.45, 0.6, 0.75):                            # in the box's shadow, within SHADOW of the hit
        assert g.state(behind(r)) == "unknown", r
    assert g.column(*behind(0.6)[:2]) == ("unknown", False)
    assert behind(0.6) in g.changed or g.delta(5.0)        # the planner hears it in the next map/cells


def test_shadow_is_bounded_and_spares_old_walls_and_open_cells():
    g = mapped_room()
    wall = cell_of((HALF, 0.0, Z))
    beside = cell_of((0.2, -0.5, Z))                       # free, still crossed by rays after the change
    g.begin_change(5.0)
    for _ in range(2):
        g.add_scan((0.0, 0.0, Z), sweep((0.0, 0.0, Z), box=True))
    assert g.state(behind(0.30 + SHADOW + 0.1)) == "seen"   # beyond SHADOW: left as it was
    assert g.cells[wall]["occupied"]                         # a wall is never forgotten
    assert g.state(beside) == "seen" and not g.cells[beside]["occupied"]


def test_a_fresh_look_from_elsewhere_re_earns_the_free_cells():
    g = mapped_room()
    g.begin_change(5.0)
    for _ in range(2):
        g.add_scan((0.0, 0.0, Z), sweep((0.0, 0.0, Z), box=True))
    assert g.state(behind(0.6)) == "unknown"
    side = (0.6, -0.6, Z)                                  # the Scout moves round the debris and looks again
    for _ in range(2):
        g.add_scan(side, sweep(side, box=True))
    assert g.state(behind(0.6)) == "seen" and not g.cells[behind(0.6)]["occupied"]
    g.add_scan((0.0, 0.0, Z), sweep((0.0, 0.0, Z), box=True))   # back at the old pose: re-seen cells stay
    assert g.state(behind(0.6)) == "seen"


def test_without_a_change_nothing_is_forgotten():
    g = Grid()
    for _ in range(3):
        g.add_scan((0.0, 0.0, Z), sweep((0.0, 0.0, Z), box=True))   # the box was always there
    before = dict(g.cells)
    g.add_scan((0.0, 0.0, Z), sweep((0.0, 0.0, Z), box=True))
    assert set(g.cells) == set(before)
