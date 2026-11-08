"""CONTACT-AFTER-FIND: in a real run log, once a casualty is found, contact and help follow.

The log is tools/demo60.py's (every lane real on coord.hub.Bus: sim, perception, planner, voice; GEMINI_MODE
off; every bus message logged as {"t", "topic", "data"}). From the first map/casualties that names a
casualty, contact_after_find() requires, in order:
- a `say` to the casualty at or after the find (the Scout speaks to them),
- a casualty/reply from that casualty after that say (they answered),
- a responder/action move on a route whose goal names that casualty, at or after the find, and no Responder
  move before the find.

The real 60 s run is opt-in like tools/tests/test_demo60.py (DEMO60_REAL=1). The checker's own rules run
every time on small hand-written logs.
"""

import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def contact_after_find(records):
    """Problems found in a demo60 log (empty list when contact and help follow the find)."""
    find = next((r for r in records if r["topic"] == "map/casualties" and r["data"]), None)
    if find is None:
        return ["no casualty found"]
    cid, t0 = find["data"][0]["id"], find["t"]
    after = [r for r in records if r["t"] >= t0]
    goals = {r["data"]["id"]: r["data"].get("goal", "") for r in records if r["topic"] == "route/proposed"}
    problems = []
    early = [r for r in records if r["t"] < t0 and r["topic"] == "responder/action" and r["data"]["action"] == "move"]
    if early:
        problems.append(f"Responder moved at {early[0]['t']} s, before {cid} was found at {t0} s")
    say = next((r for r in after if r["topic"] == "say" and r["data"].get("to") == "casualty"), None)
    if say is None:
        return [*problems, f"no say to the casualty after {cid} was found at {t0} s"]
    reply = next((r for r in records if r["t"] > say["t"] and r["topic"] == "casualty/reply"
                  and r["data"].get("id") == cid), None)
    if reply is None:
        problems.append(f"no casualty/reply from {cid} after the say at {say['t']} s")
    move = next((r for r in after if r["topic"] == "responder/action" and r["data"]["action"] == "move"
                 and cid in goals.get(r["data"]["route"], "")), None)
    if move is None:
        problems.append(f"no Responder move on a route to {cid} after the find")
    return problems


def rec(t, topic, data):
    return {"t": t, "topic": topic, "data": data}


FOUND = rec(10.0, "map/casualties", [{"id": "c1", "pos": [1, 1, 0], "confidence": 0.9}])
SAY = rec(10.0, "say", {"to": "casualty", "intent": "reassure", "text": "Can you hear me?", "lang": "auto"})
ROUTE = rec(10.1, "route/proposed", {"id": "r1", "robot": "responder", "cells": [], "goal": "deliver water to c1"})
MOVE = rec(10.2, "responder/action", {"action": "move", "route": "r1", "item": "water"})
REPLY = rec(12.0, "casualty/reply", {"id": "c1", "t": 11.5, "text": "yes", "source": "sim"})


def test_checker_accepts_contact_and_help_after_the_find():
    assert contact_after_find([FOUND, SAY, ROUTE, MOVE, REPLY]) == []


def test_checker_flags_each_missing_step():
    assert contact_after_find([SAY, ROUTE, MOVE]) == ["no casualty found"]
    assert "no say to the casualty" in contact_after_find([FOUND, ROUTE, MOVE, REPLY])[0]
    assert any("no casualty/reply" in p for p in contact_after_find([FOUND, SAY, ROUTE, MOVE]))
    assert any("no Responder move" in p for p in contact_after_find([FOUND, SAY, REPLY]))
    early = dict(MOVE, t=5.0)
    assert any("before c1 was found" in p for p in contact_after_find([ROUTE, early, FOUND, SAY, MOVE, REPLY]))


@pytest.mark.skipif(os.environ.get("DEMO60_REAL") != "1", reason="real 60 s run: set DEMO60_REAL=1")
def test_real_run_contacts_and_helps_the_casualty_after_finding_them(tmp_path):
    env = {**os.environ, "GEMINI_MODE": "off"}
    subprocess.run([sys.executable, "tools/demo60.py", "--seed", "7", "--auto-approve"],
                   check=False, cwd=ROOT, env=env, timeout=240)
    log = ROOT / "runs" / "demo60-7.jsonl"
    records = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert contact_after_find(records) == []
