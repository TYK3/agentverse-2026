"""Explicit grid-world stand-in for T24 harness development; not the full system.

Uses T23's world topology/A* baseline and the production T12 AFTERSHOCK router.
Dynamics, perception, physics validation and the human are named stand-ins.
Run explicitly with --driver tools.eval_grid:run_trial.
"""

import hashlib
import json
import random

from planner.route import find_route
from tools import scenario_fakes as scene


def scenario(seed):
    rng = random.Random(seed)
    occupied = {(x, y) for x in range(scene.W) for y in range(scene.H)
                if x in (0, scene.W - 1) or y in (0, scene.H - 1)
                or (x == scene.WALL_X and y not in scene.GAPS)}
    free = [(x, y) for x in range(2, scene.W - 2) for y in range(1, scene.H - 1)
            if x != scene.WALL_X]
    rubble = rng.sample(free, 5)
    occupied.update(rubble)
    casualty = (scene.W - 2, rng.randint(1, scene.H - 2))
    occupied.discard(casualty)
    dangerous_gap = rng.choice(scene.GAPS)
    collapse_t = rng.randint(5, 12)
    payload = {"seed": seed, "rubble": sorted(rubble), "casualty": casualty,
               "occupied": sorted(occupied), "collapse_cell": [scene.WALL_X, dangerous_gap],
               "collapse_t": collapse_t}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return payload, fingerprint


async def run_trial(*, seed, planner):
    layout, fingerprint = scenario(seed)
    occupied = {tuple(cell) for cell in layout["occupied"]}
    danger = tuple(layout["collapse_cell"])
    goal, position = tuple(layout["casualty"]), scene.START
    events = [{"t": 0, "kind": "position", "cell": [*position, 0]}]
    path, route_number = None, 0
    collapsed = set()

    def plan(t):
        nonlocal route_number
        route_number += 1
        events.append({"t": t, "kind": "route", "id": f"r{route_number}"})
        if planner == "naive":
            # Known obstacles are avoided; hazards and physics are ignored.
            return scene.astar(position, goal, occupied)
        records = [{"cell": [x, y, 0], "state": "seen", "occupied": (x, y) in occupied}
                   for x in range(scene.W) for y in range(scene.H)]
        hazards = [{"cell": [*danger, 0], "status": "collapsed" if collapsed else "at_risk",
                    "why": "grid-world scripted collapse", "estimate": True}]
        result = find_route({"t": t, "res": scene.RES, "cells": records}, hazards,
                            (*position, 0), (*goal, 0))
        if result["status"] != "ok":
            return None
        return [tuple(cell[:2]) for cell in result["cells"]]

    for t in range(80):
        if t == layout["collapse_t"]:
            collapsed.add(danger)
            events.append({"t": t, "kind": "collapsed", "cells": [[*danger, 0]]})
            if planner == "aftershock":
                path = None
        if path is None:
            path = plan(t)
            if not path:
                break
            # A simulated test operator, never a live person, approves this trial route.
            if planner == "aftershock":
                events.append({"t": t, "kind": "approval", "id": f"g{route_number}",
                               "approved": True})
        if position == goal:
            break
        if len(path) > 1:
            position = path[1]
            path = path[1:]
        events.append({"t": t + 1, "kind": "position", "cell": [*position, 0]})
    return {"seed": seed, "planner": planner, "goal": [*goal, 0], "events": events,
            "completed": True, "backend": "T23-grid-world / T12-router",
            "stand_ins": ["grid-dynamics", "oracle-map", "scripted-collapse",
                          "test-operator", "no-MuJoCo-verification"],
            "scenario_sha256": fingerprint, "scenario": layout}
