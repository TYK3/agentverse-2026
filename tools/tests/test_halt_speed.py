"""HALT-SPEED: a logged B2 halt has near-zero speed on its actual simulation tick.

Definition: a blocked/arrived/idle pose must appear within run_b2.STOP_WINDOW
(3 sim seconds) after the slab shift, with <=0.01 m/s displacement speed on
that exact 0.1-second tick. Motion before the halt must also be demonstrated.
The runner logs poses at 1 Hz, not velocities: passive tick observations avoid
mistaking a whole second of travel before arrival for the final halted speed.
"""

import copy
import json
import math

import pytest

from sim.levels import LevelWorld
from tools import run_b2

HALTED = {"blocked", "arrived", "idle"}
HALT_SPEED_MPS = 0.01


@pytest.fixture(scope="module")
def recording(tmp_path_factory):
    ticks = []
    tick = LevelWorld.tick

    def observe_tick(world, dt=0.1):
        before_t, before_pos = world.t, world.pos.tolist()
        result = tick(world, dt)
        ticks.append({"t": round(world.t, 2), "dt": world.t - before_t,
                      "before": before_pos, "pos": world.pos.tolist(), "state": world.state})
        return result

    with pytest.MonkeyPatch.context() as observe:
        observe.setattr(LevelWorld, "tick", observe_tick)
        _, path = run_b2.run(seed=0, floor="B2", out_dir=tmp_path_factory.mktemp("halt-speed-b2"))
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return records, ticks


def speed(tick):
    assert tick["dt"] == pytest.approx(0.1)
    return math.dist(tick["before"], tick["pos"]) / tick["dt"]


def assert_halt_speed(records, ticks):
    shifts = [r for r in records if r["kind"] == "shift"]
    assert len(shifts) == 1 and shifts[0]["level"] == "B2"
    shifted = shifts[0]["t"]
    halts = [r for r in records if r["kind"] == "pose" and r["state"] in HALTED
             and shifted < r["t"] <= shifted + run_b2.STOP_WINDOW]
    assert halts, "a real logged halt is required within 3 sim seconds of the slab shift"
    by_time = {t["t"]: t for t in ticks}
    for halt in halts:
        actual = by_time[halt["t"]]
        assert actual["state"] == halt["state"]
        assert [round(v, 3) for v in actual["pos"]] == halt["pos"]
        assert speed(actual) <= HALT_SPEED_MPS, "a halted robot must not keep travelling"
    first = halts[0]
    assert any(shifted < t["t"] < first["t"] and t["state"] == "moving" and speed(t) > 0.05
               for t in ticks), "the post-shift robot must actually move before halting"
    return halts


def test_real_b2_logged_halt_has_near_zero_tick_speed(recording):
    assert_halt_speed(*recording)


@pytest.mark.parametrize("mutation", ["drifting_halt", "missing_halt", "late_halt"])
def test_real_recording_mutations_cannot_pass_halt_speed(recording, mutation):
    records, ticks = copy.deepcopy(recording)
    halts = assert_halt_speed(records, ticks)
    if mutation == "drifting_halt":
        actual = next(t for t in ticks if t["t"] == halts[0]["t"])
        # Retain the logged final pose, but simulate 3 cm of continued travel
        # on its 0.1 s halt tick: 0.3 m/s must fail, regardless of the state label.
        actual["before"][0] = actual["pos"][0] - 0.03
    elif mutation == "missing_halt":
        for halt in halts:
            records.remove(halt)
    else:
        shifted = next(r["t"] for r in records if r["kind"] == "shift")
        for halt in halts:
            halt["t"] = shifted + run_b2.STOP_WINDOW + 0.1
    with pytest.raises(AssertionError):
        assert_halt_speed(records, ticks)
