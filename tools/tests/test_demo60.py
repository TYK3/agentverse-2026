"""demo60's verdict is a pure function of the log, so it is tested on hand-made events.

The 60 s real run itself is opt-in (DEMO60_REAL=1), since it needs MuJoCo and a minute of wall time.
"""

import os
import subprocess
import sys

import pytest

from tools.demo60 import STEPS, agree, evaluate, shift_cell


def pose(t, state, route, sim_t=None):
    d = {"scout": [0, 0, 0.075], "scout_state": "moving", "responder": [0, 0, 0.05],
         "responder_state": state, "responder_route": route}
    if sim_t is not None:
        d["sim_t"] = sim_t
    return (t, "_probe/pose", d)


def full_run():
    return [
        (1.0, "scene/loaded", {"scene": "backup", "blocks": []}),
        (5.0, "map/casualties", [{"id": "c1", "pos": [1, 1, 0], "confidence": 0.9, "clues": [], "vitals": {}}]),
        (5.1, "route/proposed", {"id": "r1", "cells": [[0, 0, 0]]}),
        (5.1, "route/verified", {"id": "r1", "ok": True, "unstable_cells": [], "detail": "ok"}),
        (5.2, "permit/route", {"route": "r1", "granted": True, "reason": "verified and clear", "evidence": []}),
        pose(6.0, "moving", "r1", sim_t=5.5),
        (7.0, "_runner/action", {"action": "inject", "cell": [3, 3, 0], "block": "x1", "route": "r1",
                                 "in_scout_view": True}),
        (8.0, "permit/route", {"route": "r1", "granted": False, "reason": "revoked: LiDAR hit", "evidence": []}),
        pose(8.5, "frozen", "r1", sim_t=8.0),
        (10.0, "permit/route", {"route": "r2", "granted": True, "reason": "verified and clear", "evidence": []}),
        pose(10.5, "moving", "r2", sim_t=10.0),
    ]


def test_a_full_run_passes_every_step_with_its_time():
    s = evaluate(full_run())
    assert s["failed"] == [] and s["passed"] == list(STEPS)
    assert s["steps"]["permit revoked after the shift"]["t"] == 8.0
    assert s["steps"]["Responder moving again"]["detail"] == "on r2"


def test_sim_rate_is_sim_seconds_per_wall_second():
    assert evaluate(full_run())["sim_seconds_per_wall_second"] == pytest.approx(4.5 / 4.5)


def test_without_a_shift_the_recheck_steps_fail():
    events = [e for e in full_run() if e[1] != "_runner/action"]
    s = evaluate(events)
    assert "shift dropped on the route" in s["failed"]
    assert "permit revoked after the shift" in s["failed"]
    assert "Responder moving" in s["passed"]


def test_a_revocation_before_the_shift_does_not_count():
    events = full_run()
    events.insert(5, (5.5, "permit/route", {"route": "r1", "granted": False, "reason": "early", "evidence": []}))
    events = [e for e in events if not (e[1] == "permit/route" and e[0] == 8.0)]
    s = evaluate(events)
    assert "permit revoked after the shift" in s["failed"]


def test_still_driving_the_revoked_route_fails_the_stop():
    events = [e if e[0] != 8.5 else pose(8.5, "moving", "r1") for e in full_run()]
    events = [e for e in events if e[0] != 10.5]
    s = evaluate(events)
    assert "Responder off the revoked route" in s["failed"]


def test_agree_compares_passed_steps_only():
    a = evaluate(full_run())
    b = evaluate(full_run())
    c = evaluate([e for e in full_run() if e[1] != "_runner/action"])
    assert agree([a, b]) and not agree([a, c]) and agree([a])


def test_shift_cell_prefers_a_visible_cell_ahead_and_skips_the_goal():
    cells = [[i, 0, 0] for i in range(40)]
    cell, seen = shift_cell(cells, (0.025, 0.025), ahead=0.5)
    assert cell == [10, 0, 0] and seen is False
    cell, seen = shift_cell(cells, (0.025, 0.025), ahead=0.5, visible=lambda c: c[0] >= 20)
    assert cell == [20, 0, 0] and seen is True
    cell, seen = shift_cell(cells, (0.025, 0.025), ahead=0.5, visible=lambda c: False)
    assert cell == [10, 0, 0] and seen is False                   # falls back to the first cell ahead
    assert shift_cell(cells[:12], (0.025, 0.025), ahead=0.5) == (None, False)   # only goal cells left
    assert shift_cell([], (0, 0)) == (None, False)


@pytest.mark.skipif(os.environ.get("DEMO60_REAL") != "1", reason="real 60 s run: set DEMO60_REAL=1")
def test_real_run_writes_a_summary(tmp_path):
    out = tmp_path / "s.json"
    env = {**os.environ, "GEMINI_MODE": "off"}
    subprocess.run([sys.executable, "tools/demo60.py", "--seed", "7", "--auto-approve", "--summary-out", str(out)],
                   check=False, env=env, timeout=240)
    import json
    s = json.loads(out.read_text())
    assert s["steps"]["scene loaded"]["ok"] and set(s["passed"]) | set(s["failed"]) == set(STEPS)
