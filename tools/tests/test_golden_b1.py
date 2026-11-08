"""GOLDEN-B1 (ref S1): event-order regression against one passing L1 -> B1 descent.

The golden (tools/tests/golden/b1_descent.jsonl) is a real, unscripted sim.demo_descent run.
If a deliberate change alters the descent, regenerate it with
`GEMINI_MODE=off python -m tools.tests.golden.make_b1` and say so in the PR.
"""

import itertools
import json
import math

import pytest

from tools.tests.golden import make_b1

T_TOL = 1.0        # sim seconds
POS_TOL = 0.05     # metres
ORDER = ["L1", "ground", "B1"]


def load():
    return [json.loads(line) for line in make_b1.GOLDEN.read_text().splitlines()]


def levels_in_order(events):
    """Floors in the order the decisions were made on them (time on a ramp is not a floor)."""
    return [k for k, _ in itertools.groupby(e["level"] for e in events if e["level"] != "ramp")]


def test_golden_shape_and_order():
    lines = load()
    meta, events, summary = lines[0], lines[1:-1], lines[-1]
    assert meta["kind"] == "meta" and meta["floor"] == "B1" and summary["kind"] == "summary"
    assert all(e["kind"] == "event" for e in events) and 50 < len(events) < 400
    ts = [e["t"] for e in events]
    assert ts == sorted(ts) and ts[0] == 0.0 and ts[-1] <= summary["t"]
    assert levels_in_order(events) == ORDER == summary["levels"]
    assert summary["reached"] is True and summary["responder_route"] == "ok"
    assert summary["plans"] == len(events)
    assert {e["action"] for e in events} <= {"explore", "probe", "route"}
    first_b1 = next(i for i, e in enumerate(events) if e["level"] == "B1")
    assert all(e["level"] in ("B1", "ramp") for e in events[first_b1:])   # never climbs back
    assert {e["level"] for e in events} <= {*ORDER, "ramp"}
    assert events[-1]["target"][2] == pytest.approx(-0.6)           # last decision on the B1 floor


def test_golden_has_no_host_details():
    text = make_b1.GOLDEN.read_text()
    for bad in ("/home/", "/workspace", "/Users/", "wall", "\\\\"):
        assert bad not in text
    assert len(text) < 50_000


def test_events_parser_rejects_odd_lines():
    assert make_b1.events(["   3.5s L1     explore -> [0.62, 1.52, 0.6] (arrived)"]) == [
        {"t": 3.5, "level": "L1", "action": "explore", "target": [0.62, 1.52, 0.6], "status": "arrived"}]
    with pytest.raises(ValueError):
        make_b1.events(["something else"])


def test_live_descent_matches_golden():
    pytest.importorskip("mujoco")
    from sim.demo_descent import run

    live = json.loads("[" + ",".join(make_b1.record(run(floor="B1")).splitlines()) + "]")
    gold = load()
    hint = "B1 descent changed; if deliberate, regenerate: python -m tools.tests.golden.make_b1"
    ev_live, ev_gold = live[1:-1], gold[1:-1]
    assert levels_in_order(ev_live) == ORDER, hint
    assert [(e["level"], e["action"], e["status"]) for e in ev_live] == \
        [(e["level"], e["action"], e["status"]) for e in ev_gold], hint
    for a, b in zip(ev_live, ev_gold, strict=True):
        assert abs(a["t"] - b["t"]) <= T_TOL, hint
        assert math.dist(a["target"], b["target"]) <= POS_TOL, hint
    s_live, s_gold = live[-1], gold[-1]
    assert s_live["reached"] and s_live["levels"] == s_gold["levels"], hint
    assert s_live["goal_cell"] == s_gold["goal_cell"] and abs(s_live["t"] - s_gold["t"]) <= T_TOL, hint
