"""RESCUE-RUNNER: one real run that chains the descents B1 > B2 > B3 into one log.

    GEMINI_MODE=off python tools/run_levels.py          # prints each step, writes runs/levels-<seed>.jsonl

One LevelWorld, one multi-level map and one planner for the whole run (no reset between legs): the
Scout starts on L1, finds its own way to casualty c1 beside the B1 goal, then from there to c2 in B2,
then to c3 in B3, with the same closed loop as sim.demo_descent (sim, perception.levels and
planner.levels used as they are; no lane code changed, nothing about the routes scripted).

runs/levels-<seed>.jsonl, one record per line {"t": sim seconds, "kind": ...}: "meta", "pose" (1 Hz),
"level" (each floor reached), "plan" (each decision: leg, why, target, state), "leg" (each goal
reached or not), "step" (each check, ok or FAIL) and "summary". evaluate() turns the records into
the verdict, so the same log always gives the same result. Exit 0 only if every step passed.
(Named run_levels.py: tools/run_rescue.py is the hub-level runner in open PR #52.)
"""

import argparse
import json
import math
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LEGS = ("B1", "B2", "B3")
CASUALTY = {"B1": "c1", "B2": "c2", "B3": "c3"}
ORDER = ["L1", "ground", "B1", "B2", "B3"]
MAX_JUMP = 0.035          # metres per 0.1 s tick (0.3 m/s plus a ramp's rise), as tools/run_b2.py
NEAR = 0.15               # metres: at the goal, as sim.demo_descent


def steps():
    return ([f"reached {CASUALTY[f]} on {f}" for f in LEGS] +
            ["levels in order L1 > ground > B1 > B2 > B3", "no teleport",
             "route over the scouted map from L1 to B3"])


def evaluate(records):
    """records -> {"steps": [(name, ok, detail)], "failed": [names]}; pure, works on a saved log."""
    legs = {r["floor"]: r for r in records if r["kind"] == "leg"}
    levels = [r["level"] for r in records if r["kind"] == "level"]
    summ = next((r for r in records if r["kind"] == "summary"), {})
    out = []
    for f in LEGS:
        leg = legs.get(f)
        out.append((f"reached {CASUALTY[f]} on {f}", bool(leg and leg["reached"]),
                    f"t={leg['t']}" if leg else "leg not run"))
    out.append(("levels in order L1 > ground > B1 > B2 > B3", levels == ORDER, ">".join(levels)))
    jump = summ.get("max_jump")
    out.append(("no teleport", jump is not None and jump <= MAX_JUMP, f"max_jump={jump}"))
    route = summ.get("responder_route")
    out.append(("route over the scouted map from L1 to B3", route == "ok", f"status={route}"))
    return {"steps": out, "failed": [n for n, ok, _ in out if not ok]}


def run(seed=0, max_t=900.0, verbose=False):
    """The real chained run; returns the list of records."""
    import numpy as np

    from perception.levels import GridLevels
    from planner.levels import Levels, find_route, waypoints
    from sim import demo_descent as dd
    from sim.levels import LevelWorld, max_jump

    random.seed(seed)
    np.random.seed(seed)
    w, gl = LevelWorld(render=False), GridLevels(dd.RES)
    records = [{"t": 0.0, "kind": "meta", "seed": seed, "legs": list(LEGS), "source": "tools/run_levels.py"}]

    def rec(kind, **kv):
        records.append({"t": round(float(w.t), 1), "kind": kind, **kv})
        if verbose and kind not in ("pose",):
            print(json.dumps(records[-1]))

    rec("level", level=w.level())
    last = w.level()
    next_pose, frame = 0.0, 0
    for floor in LEGS:
        goal = dd.GOALS[floor]
        goal_cell = dd.cell(*goal)
        probing, reached, stuck = None, False, None
        while w.t < max_t:
            stopped = w.state != "moving"
            frame += 1
            if stopped or frame % dd.SCAN_EVERY == 0:
                gl.add_sensors(w.sensors_message(camera=False))
            if stopped:
                here = w.pos
                if math.hypot(here[0] - goal[0], here[1] - goal[1]) < NEAR and w.level() == floor:
                    reached = True
                    break
                if probing is not None and w.state == "blocked" and \
                        dd.cell(*here[:2], w.floor_z)[:2] != list(probing[:2]):
                    gl.refuse(probing)
                probing = None
                snapshot = gl.message(w.t, everything=True)
                plan = find_route(snapshot, [], dd.cell(here[0], here[1], w.floor_z), goal_cell)
                target, why = None, plan["status"]
                if plan["status"] == "ok":
                    wps = waypoints(plan["cells"], dd.RES)
                    target, why = (wps[0] if len(wps) == 1 or dd._near(here, wps[0]) is False else wps[1]), "route"
                elif plan["status"] == "explore":
                    wps = waypoints(plan["cells"], dd.RES)
                    if len(plan["cells"]) > 2:
                        target = wps[0] if not dd._near(here, wps[0]) else wps[min(1, len(wps) - 1)]
                    else:
                        probe = dd.probe_target(w, plan["frontier"], goal_cell, Levels(snapshot))
                        target, why = (probe[0] if probe else None), "probe"
                        probing = probe[1] if probe else None
                if target is None:
                    stuck = plan.get("reason") or "no probe direction"
                    break
                rec("plan", leg=floor, why=why, target=[round(float(v), 2) for v in target], state=w.state)
                w.goto({"target": target, "reason": f"rescue-runner {floor} {why}"})
            w.tick(dd.DT)
            if w.level() not in ("ramp", last):
                last = w.level()
                rec("level", level=last)
            if w.t >= next_pose:
                rec("pose", level=w.level(), pos=[round(float(v), 3) for v in w.pos])
                next_pose += 1.0
        rec("leg", floor=floor, casualty=CASUALTY[floor], reached=reached,
            **({"stuck": stuck} if stuck else {}) if not reached else {})
        if not reached:
            break
    start = w.trace[0]
    final = gl.message(w.t, everything=True)
    here = w.pos
    responder = find_route(final, [], dd.cell(start[1], start[2], start[3] - 0.075),
                           dd.cell(here[0], here[1], w.floor_z))
    rec("summary", max_jump=round(float(max_jump(w.trace)), 4), responder_route=responder["status"],
        final_pos=[round(float(v), 3) for v in here], plans=sum(r["kind"] == "plan" for r in records))
    for name, ok, detail in evaluate(records)["steps"]:
        rec("step", name=name, ok=ok, detail=detail)
    return records


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--max-t", type=float, default=900.0, help="sim seconds allowed for all three legs")
    p.add_argument("--out", default=None, help="default runs/levels-<seed>.jsonl")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args(argv)
    records = run(a.seed, a.max_t, a.verbose)
    out = pathlib.Path(a.out or ROOT / "runs" / f"levels-{a.seed}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records))
    verdict = evaluate(records)
    for name, ok, detail in verdict["steps"]:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: {detail}")
    n = len(verdict["steps"])
    print(f"{n - len(verdict['failed'])}/{n} steps passed" +
          (f"; failed: {', '.join(verdict['failed'])}" if verdict["failed"] else "") + f"  log: {out.name}")
    return 0 if not verdict["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
