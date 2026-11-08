"""SLAB-STOP-ONCE: the Scout stops for a shifted slab once, short of it, and then drives on without
stopping for it again (no stop / start / stop loop in front of the slab).

Real rescues with a slab shift (tools/run_b2.py --floor B2 and B3, seed 0). The run log has poses at
1 Hz only, so sim.levels.LevelWorld is wrapped (monkeypatch, no lane or runner code changed) to book
the Scout's state at every tick. After the shift there must be exactly one entry into "blocked",
within run_b2.STOP_WINDOW of the shift, with the Scout clear of the slab. Synthetic tick lists pin the
counting. Skips the real runs without MuJoCo.
"""

import json
import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

SLAB_HALF = 0.12   # metres, tools/run_b2.SLAB_HALF in x and y


def stops(ticks, t0):
    """[(t, (x, y))] each time the state turns "blocked" at or after t0; ticks are (t, state, (x, y))."""
    out, prev = [], None
    for t, state, xy in ticks:
        if t >= t0 and state == "blocked" and prev != "blocked":
            out.append((t, xy))
        prev = state
    return out


def test_one_stop_is_counted_once_however_long_it_lasts():
    ticks = [(1.0, "moving", (0, 0)), (1.1, "blocked", (0, 0)), (1.2, "blocked", (0, 0)), (1.3, "moving", (0, 0))]
    assert stops(ticks, 1.0) == [(1.1, (0, 0))]


def test_a_stop_start_stop_loop_counts_twice():
    ticks = [(1.0, "blocked", (0, 0)), (1.1, "moving", (0, 0)), (1.2, "blocked", (0, 0))]
    assert len(stops(ticks, 0.0)) == 2


def test_stops_before_the_shift_are_ignored():
    ticks = [(0.5, "blocked", (0, 0)), (0.6, "moving", (0, 0)), (1.5, "arrived", (0, 0))]
    assert stops(ticks, 1.0) == []


@pytest.mark.parametrize("floor", ["B2", "B3"])
def test_real_scout_stops_once_for_the_slab(floor, tmp_path, monkeypatch):
    pytest.importorskip("mujoco")
    import run_b2

    import sim.levels as sl

    ticks = []

    class Watched(sl.LevelWorld):
        def tick(self, dt=0.1):
            out = super().tick(dt)
            ticks.append((round(self.t, 2), self.state, tuple(float(v) for v in self.pos[:2])))
            return out

    monkeypatch.setattr(sl, "LevelWorld", Watched)
    verdict, path = run_b2.run(seed=0, out_dir=tmp_path, floor=floor)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    shift = next((r for r in records if r["kind"] == "shift"), None)
    assert shift is not None, f"no slab shift on {floor}"

    found = stops(ticks, shift["t"])
    assert len(found) == 1, f"expected one stop for the slab, got {found}"
    t, xy = found[0]
    assert t <= shift["t"] + run_b2.STOP_WINDOW, f"stopped at {t} s, shift at {shift['t']} s"
    assert math.dist(xy, shift["xy"]) > SLAB_HALF, f"stopped at {xy}, inside the slab at {shift['xy']}"
    assert "Scout reached the casualty on the target floor" in verdict["passed"]
