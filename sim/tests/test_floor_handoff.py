"""Floor handoffs on the descent B1, then B2, then B3 (sim/levels.py).

One LevelWorld drives the real ramps from L1 down to B3. The world is not rebuilt
between basements. At each floor change the Scout's pose carries over from the
previous tick (no reset to the start, no jump), and a casualty id seen before the
change is the same id afterwards: no duplicate and no rename.

The legs are the ramp path from sim/tests/test_b3_descent.py, plus a stop beside
each casualty before the next ramp so that id is seen while the Scout is still on
that floor. Floor heights are the SCENE-B2 levels: L1 0.6, ground 0, B1 -0.6,
B2 -1.2, B3 -1.8.
"""

import math
from itertools import pairwise

import pytest

from sim import sensors
from sim.levels import LEVEL_Z, RIDE, LevelWorld

# Same no-teleport bound as sim/tests/test_descent.py: 0.3 m/s over a 0.1 s tick, plus a ramp's rise.
MAX_STEP = 0.035
DT = 0.1
BASEMENTS = ("B1", "B2", "B3")
CASUALTY = {"B1": "c1", "B2": "c2", "B3": "c3"}   # sim/scenes/make_levels.py


def legs():
    """Waypoints down every ramp, with a visit beside c1, c2 and c3 before leaving that basement."""
    b1, b2, b3 = LEVEL_Z["B1"], LEVEL_Z["B2"], LEVEL_Z["B3"]
    return [
        (1.2, 2.1, 0.6), (3.8, 2.1, 0.0), (3.8, 0.3, 0.0), (1.3, 0.3, b1),
        (1.5, 1.55, b1), (0.75, 1.55, b1),                 # beside c1, then down R3
        (1.35, 1.5, b1), (2.3, 2.1, b1), (4.75, 2.1, b2),
        (4.75, 1.5, b2), (0.75, 1.5, b2), (0.75, 0.8, b2),  # beside c2
        (0.75, 1.5, b2), (4.75, 1.5, b2), (4.75, 0.6, b2),  # back to R4 along the clear corridor
        (4.75, 0.3, b2), (2.0, 0.3, b3), (2.0, 1.0, b3), (0.75, 1.6, b3),  # beside c3
    ]


def roster(world):
    """id -> (geom id, position) for every casualty marker. Ids must already be unique."""
    out = {}
    for name, geom, _voice in world.casualties:
        assert name not in out, name
        out[name] = (geom, tuple(float(v) for v in world.d.geom_xpos[geom]))
    return out


def seen_ids(world):
    """Casualty ids in line of sight and within thermal range of the Scout."""
    origin = world.sensor_origin
    seen = []
    for name, geom, _voice in world.casualties:
        hit, dist = sensors.first_hit(world.m, world.d, origin, world.d.geom_xpos[geom], world.scout)
        if hit == geom and float(dist) <= sensors.THERMAL_RANGE:
            seen.append(name)
    return tuple(seen)


def sample(world):
    return {
        "t": world.t,
        "level": world.level(),
        "pos": tuple(float(v) for v in world.pos),
        "seen": seen_ids(world),
        "roster": roster(world),
    }


def handoff_window(samples, src, dst):
    """From the last tick still on src to the first tick on dst, ramp included.

    Returns (window, index of the last src sample).
    """
    levels = [s["level"] for s in samples]
    first = next(i for i, level in enumerate(levels) if level == dst and src in levels[:i])
    last = max(i for i in range(first) if levels[i] == src)
    return samples[last:first + 1], last


@pytest.fixture(scope="module")
def descent():
    """One continuous LevelWorld run, sampled every tick."""
    world = LevelWorld(render=False)
    samples = [sample(world)]
    for leg in legs():
        world.goto({"target": list(leg), "reason": "floor handoff"})
        for _ in range(900):
            world.tick(DT)
            samples.append(sample(world))
            if world.state != "moving":
                break
        assert world.state == "arrived", (
            leg, world.state, world.level(), [round(float(v), 3) for v in world.pos])
    return {"samples": samples, "spawn": samples[0]["pos"]}


def test_pose_carries_across_each_basement_handoff(descent):
    """B1 to B2 and B2 to B3 stay on the ramp: each tick is a short step, and time does not restart."""
    samples, spawn = descent["samples"], descent["spawn"]
    order = []
    for level in (s["level"] for s in samples if s["level"] != "ramp"):
        if not order or order[-1] != level:
            order.append(level)
    assert order == ["L1", "ground", "B1", "B2", "B3"]

    for src, dst in pairwise(BASEMENTS):
        window, _last = handoff_window(samples, src, dst)
        assert window[0]["level"] == src and window[-1]["level"] == dst
        assert "ramp" in {s["level"] for s in window}, (src, dst)
        for before, after in pairwise(window):
            step = math.dist(before["pos"], after["pos"])
            assert step < MAX_STEP, (src, dst, round(step, 4), before["pos"], after["pos"])
            assert after["t"] == pytest.approx(before["t"] + DT)
            assert math.dist(after["pos"], spawn) > 1.0
        assert window[-1]["pos"][2] == pytest.approx(LEVEL_Z[dst] + RIDE, abs=0.02)

    steps = [math.dist(a["pos"], b["pos"]) for a, b in pairwise(samples)]
    assert steps and max(steps) < MAX_STEP


def test_casualty_ids_stay_stable_across_each_basement_handoff(descent):
    """An id seen on a floor is the same marker after the handoff: same geom, same place, no second copy."""
    samples = descent["samples"]
    names = [tuple(s["roster"]) for s in samples]
    assert names[0] == ("c1", "c2", "c3")
    assert all(n == names[0] for n in names), "a casualty id appeared, vanished or was renamed"
    for taken in samples:
        assert len(taken["seen"]) == len(set(taken["seen"]))

    first = samples[0]["roster"]
    for later in samples[1:]:
        for cid, (geom, pos) in first.items():
            assert later["roster"][cid][0] == geom, cid
            assert later["roster"][cid][1] == pytest.approx(pos, abs=1e-6)

    for src, dst in pairwise(BASEMENTS):
        window, last = handoff_window(samples, src, dst)
        seen_before = set()
        for taken in samples[: last + 1]:
            if taken["level"] == src:
                seen_before.update(taken["seen"])
        kept = CASUALTY[src]
        assert kept in seen_before, (src, sorted(seen_before))
        before, after = window[0]["roster"], window[-1]["roster"]
        assert after[kept][0] == before[kept][0]
        assert after[kept][1] == pytest.approx(before[kept][1], abs=1e-6)
        arrived = CASUALTY[dst]
        assert arrived != kept and after[arrived][0] != after[kept][0]

    on_b3 = [s for s in samples if s["level"] == "B3"]
    assert "c3" in set().union(*(s["seen"] for s in on_b3))
    assert set(samples[-1]["roster"]) == {"c1", "c2", "c3"}
