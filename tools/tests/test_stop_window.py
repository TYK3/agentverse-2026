"""STOP-WINDOW: after the slab shift, every robot halts inside STOP_WINDOW and a plan follows.

Seed 0 of tools/run_b2.py with GEMINI_MODE=off. The live run finishes in under 30 s, so this
test drives that runner.

A halt is zero velocity, or a blocked, idle or stop status. A waypoint "arrived" sample keeps
moving on the next pose, so it is outside that rule. STOP_WINDOW in tools/run_b2.py is the
sim-time stop window, in seconds after the shift.
"""

import json
import math

import pytest

from tools.run_b2 import STOP_WINDOW, run

# Statuses that count as a halt. "stop_and_recheck" is included so the check passes once that
# event exists; it is not in the seed-0 log today.
HALT_STATES = frozenset({"blocked", "idle", "stop"})


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _robot(row):
    named = row.get("robot") or row.get("name")
    if named in ("scout", "responder"):
        return named
    if row.get("kind") == "pose":
        return "scout"  # run_b2 pose records are the Scout; they carry no robot field
    return None


def _explicit_speed(row):
    for key in ("speed", "vel", "velocity"):
        if key not in row:
            continue
        value = row[key]
        if isinstance(value, (int, float)):
            return abs(float(value))
        if isinstance(value, (list, tuple)) and value:
            return math.hypot(*(float(v) for v in value[:3]))
    return None


def _halted(row, prev):
    state = row.get("state")
    if state is None:
        state = row.get("status")
    if state in HALT_STATES or (isinstance(state, str) and state.startswith("stop")):
        return True
    if row.get("kind") in ("stop", "stop_and_recheck"):
        return True
    speed = _explicit_speed(row)
    if speed == 0.0:
        return True
    same_place = (prev is not None and row.get("pos") and prev.get("pos") and row["t"] > prev["t"]
                  and math.dist(row["pos"][:2], prev["pos"][:2]) == 0.0)
    return bool(same_place)


def _halt_times(rows, shift_t):
    """robot -> (index, sim time) of the first halt at or after shift_t. Absent robots are omitted."""
    order, prev, halts = [], {}, {}
    for index, row in enumerate(rows):
        robot = _robot(row)
        kind = row.get("kind")
        if robot is None or kind not in ("pose", "stop", "stop_and_recheck"):
            continue
        if robot not in order:
            order.append(robot)
        if robot not in halts and row["t"] >= shift_t and _halted(row, prev.get(robot)):
            halts[robot] = (index, row["t"])
        if kind == "pose":
            prev[robot] = row
    return order, halts


def _plan_after(rows, index):
    """The recheck is a plan event strictly after the halt record."""
    for row in rows[index + 1:]:
        if row.get("kind") == "plan":
            return row
    return None


@pytest.mark.slow
@pytest.mark.xfail(strict=True, reason="ADD-BLOCK-Z / missing stop_and_recheck")
def test_every_robot_halts_inside_stop_window_then_a_plan_follows(tmp_path, monkeypatch):
    pytest.importorskip("mujoco")
    monkeypatch.setenv("GEMINI_MODE", "off")
    _verdict, path = run(seed=0, out_dir=tmp_path)
    rows = _records(path)
    shift = next((row for row in rows if row.get("kind") == "shift"), None)
    assert shift is not None, "seed-0 log has no slab-shift marker"
    robots, halts = _halt_times(rows, shift["t"])
    assert robots, "seed-0 log records no robot"
    problems = []
    for robot in robots:
        hit = halts.get(robot)
        if hit is None:
            problems.append(f"{robot}: no halt after the shift at t={shift['t']}")
            continue
        index, when = hit
        delay = when - shift["t"]
        if delay > STOP_WINDOW:
            problems.append(
                f"{robot}: halted at t={when} ({delay:.3f}s > STOP_WINDOW={STOP_WINDOW})")
        if _plan_after(rows, index) is None:
            problems.append(f"{robot}: halt at t={when} is not followed by a plan")
    assert not problems, "; ".join(problems)
