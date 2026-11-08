"""RADIO-ON-B3: the Responder (rover) carries a radio down to casualty c3 on B3 and sets it down there.

Needs the levels scene's Responder (#267, LEVELS-RESPONDER). Until that is on main this module skips.
1. The Scout's real closed-loop descent to B3 (sim.demo_descent: nothing scripted) builds the map.
2. planner.levels plans the Responder's route over that map, from its own cell on L1 to where the Scout
   stopped beside c3. Route cells within START_TRIM of the Responder are dropped before driving: the
   route starts at the centre of the Responder's own cell, a few cm toward the corner it is parked in,
   and heading there first trips its collision ray (a finding for the planner/sim hand-off).
3. A fresh LevelWorld runs the real sim/responder.py on that route (move, then place_supply radio).
   Its pose every second, its decisions and the radio's final pose go to a jsonl log, read back here.
Checks: the Responder arrives on B3, never moves more than MAX_MOVE per tick (no teleport), the radio is
placed and no longer held, and it rests on the B3 floor (not on a floor above) within NEAR of c3.
"""

import json
import math

import pytest

pytest.importorskip("mujoco")

NEAR = 0.5            # metres from c3 that count as delivered (the e2e runners' rule)
START_TRIM = 0.10     # metres: route cells this close to the Responder's start are dropped
MAX_MOVE = 0.035      # metres per 0.1 s tick
B3_Z = -1.8
MAX_T = 300.0         # sim seconds for the Responder's drive


def has_levels_responder():
    from sim.levels import LEVELS

    return 'name="responder"' in LEVELS.read_text(encoding="utf-8")


pytestmark = pytest.mark.skipif(not has_levels_responder(),
                                reason="levels.xml has no Responder yet (#267 LEVELS-RESPONDER)")


@pytest.fixture(scope="module")
def delivery(tmp_path_factory):
    import numpy as np

    from planner.levels import find_route
    from sim import responder as R
    from sim.demo_descent import cell, run
    from sim.levels import LevelWorld

    scout = run(max_t=600.0, floor="B3")
    w = LevelWorld(render=False)
    decisions = []
    r = R.Responder(w.m, w.d, publish=lambda topic, data: decisions.append(data), clock=lambda: w.t)
    start_xy = [float(v) for v in r.pos[:2]]
    x, y, z = scout["final_pos"]
    route = find_route(scout["map"], [], cell(start_xy[0], start_xy[1], float(r.pos[2]) - 0.05),
                       cell(x, y, z - 0.075))
    cells = [c for c in route.get("cells", [])
             if math.dist(((c[0] + 0.5) * 0.05, (c[1] + 0.5) * 0.05), start_xy) > START_TRIM]
    records = [{"t": 0.0, "kind": "route", "status": route["status"], "cells": len(cells)}]
    if cells:
        r.on_route({"id": "rb3", "robot": "responder", "cells": cells, "goal": "radio to c3", "model": "local-astar"})
        r.on_action({"action": "move", "route": "rb3", "item": "radio"})
    prev, biggest, next_pose = np.array(r.pos), 0.0, 0.0
    while w.t < MAX_T and r.state == "moving":
        r.step(0.1)
        w.tick(0.1)
        biggest = max(biggest, float(np.linalg.norm(np.array(r.pos) - prev)))
        prev = np.array(r.pos)
        if w.t >= next_pose:
            records.append({"t": round(w.t, 2), "kind": "pose", "pos": [round(float(v), 3) for v in r.pos],
                            "state": r.state})
            next_pose += 1.0
    records.append({"t": round(w.t, 2), "kind": "drive_end", "state": r.state,
                    "pos": [round(float(v), 3) for v in r.pos], "max_move": round(biggest, 4)})
    placed = r.on_action({"action": "place_supply", "route": "rb3", "item": "radio"})
    for _ in range(30):
        r.step(0.1)
        w.tick(0.1)
    radio = [round(float(v), 3) for v in w.d.xpos[w.m.body("radio").id]]
    c3 = [round(float(v), 3) for v in w.d.xpos[w.m.body("casualty_c3").id]]
    records += [{"t": round(w.t, 2), "kind": "place", "outcome": placed.get("outcome"),
                 "reason": placed.get("reason", ""), "held": r.holding("radio")},
                {"t": round(w.t, 2), "kind": "final", "radio": radio, "c3": c3},
                *({"t": d.get("t", 0), "kind": "decision", "outcome": d.get("outcome"), "reason": d.get("reason")}
                  for d in decisions if isinstance(d, dict))]
    path = tmp_path_factory.mktemp("b3radio") / "b3-radio.jsonl"
    path.write_text("".join(json.dumps(x) + "\n" for x in records), encoding="utf-8")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def one(log, kind):
    return next(x for x in log if x["kind"] == kind)


def test_a_route_to_c3_exists_over_the_scouted_map(delivery):
    route = one(delivery, "route")
    assert route["status"] == "ok" and route["cells"] > 0


def test_the_responder_drives_down_to_b3_without_teleport(delivery):
    end = one(delivery, "drive_end")
    blocked = [x["reason"] for x in delivery if x["kind"] == "decision" and x["outcome"] == "blocked"]
    assert end["state"] == "arrived", f"ended {end['state']} at {end['pos']}: {blocked[:1]}"
    assert abs(end["pos"][2] - (B3_Z + 0.05)) < 0.03
    assert end["max_move"] <= MAX_MOVE


def test_the_radio_is_set_down_by_c3_on_b3(delivery):
    place, final = one(delivery, "place"), one(delivery, "final")
    assert place["outcome"] == "done" and place["reason"].startswith("placed radio at") and not place["held"]
    radio, c3 = final["radio"], final["c3"]
    assert abs(radio[2] - B3_Z) < 0.1, f"radio at z {radio[2]}: not on B3"
    assert math.dist(radio[:2], c3[:2]) <= NEAR, f"radio {radio}, c3 {c3}"
