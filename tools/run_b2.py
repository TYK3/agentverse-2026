"""e2e-b2: a real B2 rescue with a slab shift, the stop and a fresh recheck, logged as jsonl (ref b2).

    python tools/run_b2.py                 # prints each step, writes runs/b2-<seed>.jsonl
    python tools/run_b2.py --floor B3      # e2e-b3: down to c3 in B3, runs/b3-<seed>.jsonl

The Scout starts on L1 and finds its own way down to casualty c2 in basement B2 (L1 -> ground -> B1 -> B2
on ramps R2, R1, R3) with the same closed loop as sim.demo_descent: LevelWorld physics (height only from
the floor under it), the multi-level map (perception.levels) and the multi-level A* (planner.levels).
Nothing about the route is scripted. The runner adds one unscripted change: once the Scout is on the
target floor and driving its way to the casualty (an "ok" route to it, or an explore path ending within
NEAR_GOAL of it: on B1 c1 stays unknown until close, so every plan there is explore), a slab lands on it
SHIFT_AHEAD ahead of the Scout. Not on any other explore path: there it can land in the only passage
(R3's foot, seen in a run) and test a dead end instead of a stop and recheck. Then it checks that:
  - the Scout stops short of the slab (stops or re-plans within STOP_WINDOW; never driven through),
  - the slab gets into the map from what the Scout measured (LiDAR hits or a refused step), not from
    sim truth,
  - the next route avoids the slab, and the Scout still reaches c2 on B2,
  - no move per tick was a jump (no teleport), and the map the Scout built gives a route from L1 down
    to B2 (what a Responder would follow).

The slab is a spare free body added to a copy of sim/scenes/levels.xml under runs/ (the sim's scene
files are not edited) and placed on the B2 floor by this runner; World.add_block assumes ground at z 0.

runs/b2-<seed>.jsonl: one record per line {"t": sim seconds, "kind": ..., ...}: "pose" (every 0.1 s tick),
"level" (each level reached), "plan" (each re-plan: status, why, target), "shift", "step" (each
check, ok or FAIL) and "summary". The summary record and the verdict record each carry `seed`,
the value passed to run(). evaluate() turns the records into the verdict, so the same log
always gives the same result. Exit 0 only if every step passed.
"""

import argparse
import json
import math
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RES = 0.05
FLOOR = "B2"                       # default target floor (--floor B3 for e2e-b3)
PATHS = {"B1": ["L1", "ground", "B1"], "B2": ["L1", "ground", "B1", "B2"],
         "B3": ["L1", "ground", "B1", "B2", "B3"]}
FLOOR_K = {"B1": -12, "B2": -24, "B3": -36}  # floor height / 0.05
CASUALTY = {"B1": "c1", "B2": "c2", "B3": "c3"}
SLAB_HALF = (0.12, 0.12, 0.05)     # metres: a 0.24 m x 0.24 m x 0.1 m slab
SHIFT_AHEAD = 0.3                  # metres along the route to c2 ahead of the Scout
MIN_LEFT = 0.6                     # only shift if this much of that route is left (room to go round)
NEAR_GOAL = 0.75                   # an explore path ending this close to the casualty counts as its route
MAX_JUMP = 0.035                   # metres per 0.1 s tick: 0.3 m/s plus a ramp's rise
STOP_WINDOW = 3.0                  # sim seconds after the shift for the Scout to stop or turn away

STEPS = (
    "descended level by level to the target floor",
    "slab dropped on the planned route on the target floor",
    "Scout stopped short of the slab",
    "slab mapped from the Scout's own measurements",
    "re-planned route avoids the slab",
    "Scout reached the casualty on the target floor",
    "Scout never entered the slab",
    "no teleport",
    "route over the scouted map from L1 to the target floor",
)


# ---- scene -------------------------------------------------------------------------------------
def scene_with_slab(out_dir):
    """Path of a fresh per-run copy of levels.xml in out_dir with one parked spare slab body 'x1' (no collisions,
    gravity off); removed at exit."""
    from sim.levels import LEVELS

    xml = LEVELS.read_text(encoding="utf-8")
    sx, sy, sz = SLAB_HALF
    slab = (f'    <body name="x1" pos="0 0 -3" gravcomp="1"><freejoint/>'
            f'<geom name="x1_slab" type="box" size="{sx} {sy} {sz}" density="600" contype="0" '
            f'conaffinity="0" rgba="0.6 0.45 0.35 1"/></body>\n  </worldbody>')
    xml, n = re.subn(r"\s*</worldbody>", "\n" + slab, xml, count=1)
    if n != 1:
        raise ValueError("levels.xml has no </worldbody>")
    # one file per run, so parallel runs sharing out_dir don't overwrite each other's scene
    import atexit
    import os
    import tempfile

    fd, name = tempfile.mkstemp(prefix="levels_with_slab-", suffix=".xml", dir=out_dir)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(xml)
    out = pathlib.Path(name)
    atexit.register(out.unlink, missing_ok=True)
    return out


def drop_slab(world, xy, floor_z):
    """Put slab x1 on the floor at (x, y) with collisions on, and let physics hold it there."""
    import mujoco

    m, d = world.m, world.d
    b = m.body("x1").id
    g = m.body_geomadr[b]
    m.body_gravcomp[b] = 0
    m.geom_contype[g] = m.geom_conaffinity[g] = 1
    m.body_contype[b] = m.body_conaffinity[b] = 1
    adr = m.jnt_qposadr[m.body_jntadr[b]]
    vadr = m.jnt_dofadr[m.body_jntadr[b]]
    d.qpos[adr:adr + 7] = [xy[0], xy[1], floor_z + SLAB_HALF[2] + 0.002, 1, 0, 0, 0]
    d.qvel[vadr:vadr + 6] = 0
    mujoco.mj_forward(m, d)


def footprint(xy, margin=0.0):
    """Grid columns (i, j) covered by the slab at xy, grown by margin metres."""
    sx, sy = SLAB_HALF[0] + margin, SLAB_HALF[1] + margin
    return {(i, j) for i in range(math.floor((xy[0] - sx) / RES), math.floor((xy[0] + sx) / RES) + 1)
            for j in range(math.floor((xy[1] - sy) / RES), math.floor((xy[1] + sy) / RES) + 1)}


def toward_casualty(plan, goal):
    """True if the plan is the way to the casualty: an "ok" route to it, or an "explore" path whose end is
    within NEAR_GOAL of it. On B1 c1's cell stays unknown until the Scout is almost there, so every plan is
    "explore"; an explore path elsewhere (R3's foot on B2, say) could land the slab in the only passage."""
    if plan["status"] == "ok":
        return True
    if plan["status"] != "explore" or not plan["cells"]:
        return False
    end = plan["cells"][-1]
    return math.dist(((end[0] + 0.5) * RES, (end[1] + 0.5) * RES), goal[:2]) < NEAR_GOAL


def point_ahead(cells, here, ahead=SHIFT_AHEAD):
    """(x, y) of the planned route cell about `ahead` m past the cell nearest the Scout, with at least
    MIN_LEFT of route still beyond the Scout; None if the route is too short."""
    centre = [((c[0] + 0.5) * RES, (c[1] + 0.5) * RES) for c in cells]
    if len(centre) < 2:
        return None
    near = min(range(len(centre)), key=lambda n: math.dist(centre[n], here))
    left = sum(math.dist(a, b) for a, b in zip(centre[near:], centre[near + 1:], strict=False))
    if left < MIN_LEFT:
        return None
    run = 0.0
    for n in range(near + 1, len(centre)):
        run += math.dist(centre[n - 1], centre[n])
        if run >= ahead:
            return centre[n]
    return None


# ---- the verdict (pure) ------------------------------------------------------------------------
def evaluate(records):
    """{"steps": {name: {"ok", "t", "detail"}}, "passed", "failed"} from a run's records."""
    out = {}

    def put(name, ok, t, detail):
        out[name] = {"ok": bool(ok), "t": t, "detail": detail}

    summary = next((r for r in records if r["kind"] == "summary"), {})
    floor = summary.get("floor", "B2")
    levels = [r["level"] for r in records if r["kind"] == "level"]
    want = PATHS[floor]
    put(STEPS[0], levels[:len(want)] == want, None, " -> ".join(levels) or "no level")
    shift = next((r for r in records if r["kind"] == "shift"), None)
    put(STEPS[1], shift is not None, shift and shift["t"],
        f"slab at {shift['xy']} on {shift['level']}" if shift else f"no shift (route on {floor} too short or never driven)")
    if shift:
        after = [r for r in records if r["t"] >= shift["t"]]
        stop = next((r for r in after if r["kind"] == "pose" and r["state"] in ("blocked", "arrived", "idle")
                     and r["t"] <= shift["t"] + STOP_WINDOW), None)
        replan = next((r for r in after if r["kind"] == "plan" and r["t"] > shift["t"]), None)
        put(STEPS[2], stop is not None or (replan and replan["t"] <= shift["t"] + STOP_WINDOW),
            (stop or replan or {}).get("t"),
            f"state {stop['state']}" if stop else (f"re-planned at {replan['t']} s" if replan else "kept driving"))
        mapped = next((r for r in after if r["kind"] == "mapped"), None)
        put(STEPS[3], mapped is not None and mapped["cells"] > 0, mapped and mapped["t"],
            f"{mapped['cells']} occupied cell(s) in the slab's footprint ({', '.join(mapped['sources'])})"
            if mapped else "no measured cell on the slab")
        routes = [r for r in after if r["kind"] == "plan" and r["cells"] and r["t"] > shift["t"]]
        core = {tuple(c) for c in shift["core"]}
        clear = [r for r in routes if not (core & {tuple(c[:2]) for c in r["cells"]})]
        put(STEPS[4], bool(routes) and len(clear) == len(routes), routes[0]["t"] if routes else None,
            f"{len(clear)}/{len(routes)} planned paths after the shift avoid it" if routes
            else "no planned path after the shift")
        inside = [r for r in after if r["kind"] == "pose" and tuple(r["cell"][:2]) in {tuple(c) for c in
                                                                                       shift["core"]}]
        put(STEPS[6], not inside, inside[0]["t"] if inside else None,
            f"Scout pose inside the slab at {inside[0]['t']} s" if inside else "never inside it")
    else:
        for n in (2, 3, 4, 6):
            put(STEPS[n], False, None, "no shift")
    put(STEPS[5], summary.get("reached") is True, summary.get("t"),
        f"at {summary.get('final_pos')} on {summary.get('final_level')}")
    jump = summary.get("max_jump")
    put(STEPS[7], jump is not None and jump <= MAX_JUMP, None, f"max move {jump} m per tick")
    put(STEPS[8], summary.get("route") == "ok" and summary.get("route_k") and summary["route_k"][1] <= FLOOR_K[floor],
        None, f"{summary.get('route')} k {summary.get('route_k')}")
    steps = {n: out[n] for n in STEPS}
    return {"steps": steps, "passed": [n for n in STEPS if steps[n]["ok"]],
            "failed": [n for n in STEPS if not steps[n]["ok"]]}


# ---- one run -------------------------------------------------------------------------------------
def run(seed=0, max_t=500.0, out_dir=None, verbose=False, floor=FLOOR):
    from perception.levels import GridLevels
    from planner.levels import Levels, find_route, waypoints
    from sim.demo_descent import DT, GOALS, SCAN_EVERY, _near, cell, probe_target
    from sim.levels import LevelWorld, max_jump

    out_dir = pathlib.Path(out_dir or ROOT / "runs")
    out_dir.mkdir(parents=True, exist_ok=True)
    w = LevelWorld(path=scene_with_slab(out_dir), seed=seed, render=False)
    gl = GridLevels(RES)
    goal = GOALS[floor]
    goal_cell = cell(*goal)
    records = []

    def rec(kind, **kv):
        r = {"t": round(w.t, 2), "kind": kind, **kv}
        records.append(r)
        if verbose and kind not in ("pose",):
            print(json.dumps(r)[:160])

    rec("level", level=w.level())
    last_level = w.level()
    probing, plan, frame, next_pose = None, None, 0, 0.0
    shift, mapped_done = None, False
    while w.t < max_t:
        stopped = w.state != "moving"
        frame += 1
        if stopped or frame % SCAN_EVERY == 0:
            gl.add_sensors(w.sensors_message(camera=False))
        if shift and not mapped_done:
            hit = [(c, v["source"]) for c, v in gl.cells.items()
                   if v["occupied"] and (c[0], c[1]) in shift["area"] and abs(c[2] - shift["k"]) <= 3]
            if hit:
                rec("mapped", cells=len(hit), sources=sorted({s for _, s in hit}))
                mapped_done = True
        if w.t >= next_pose:
            rec("pose", pos=[round(float(v), 3) for v in w.pos], state=w.state, level=w.level(),
                cell=cell(w.pos[0], w.pos[1], w.floor_z))
            next_pose = round(w.t + DT, 6)   # next tick; += 0.1 drifts off World.tick's clock
        if stopped:
            here = w.pos
            if math.hypot(here[0] - goal[0], here[1] - goal[1]) < 0.15 and w.level() == floor:
                break
            if probing is not None and w.state == "blocked" and cell(*here[:2], w.floor_z)[:2] != list(probing[:2]):
                gl.refuse(probing)
            probing = None
            snapshot = gl.message(w.t, everything=True)
            plan = find_route(snapshot, [], cell(here[0], here[1], w.floor_z), goal_cell)
            if plan["status"] == "ok":
                wps = waypoints(plan["cells"], RES)
                target, why = (wps[0] if len(wps) == 1 or not _near(here, wps[0]) else wps[1]), "route"
            elif plan["status"] == "explore":
                wps = waypoints(plan["cells"], RES)
                if len(plan["cells"]) > 2:
                    target, why = (wps[0] if not _near(here, wps[0]) else wps[min(1, len(wps) - 1)]), "explore"
                else:
                    probe = probe_target(w, plan["frontier"], goal_cell, Levels(snapshot))
                    target, why = (probe[0] if probe else None), "probe"
                    probing = probe[1] if probe else None
            else:
                rec("plan", status=plan["status"], why=plan.get("reason"), cells=[])
                break
            if target is None:
                rec("plan", status="stuck", why="no probe direction", cells=[])
                break
            rec("plan", status=plan["status"], why=why, target=[round(float(v), 2) for v in target],
                cells=plan["cells"])
            w.goto({"target": target, "reason": f"b2 {why}"})
        # The unscripted change: once, on the target floor, on the route the Scout is driving.
        if (shift is None and w.level() == floor and w.state == "moving" and plan
                and len(plan["cells"]) > 2 and toward_casualty(plan, goal)):
            xy = point_ahead(plan["cells"], w.pos[:2])
            if xy is not None:
                drop_slab(w, xy, w.floor_z)
                area = footprint(xy, margin=0.05)
                shift = {"xy": xy, "area": area, "k": cell(*xy, w.floor_z)[2]}
                rec("shift", xy=[round(v, 3) for v in xy], level=w.level(), footprint=sorted(map(list, area)),
                    core=sorted(map(list, footprint(xy))), scout=[round(float(v), 3) for v in w.pos])
        w.tick(DT)
        if w.level() not in ("ramp", last_level):
            last_level = w.level()
            rec("level", level=last_level)

    here = w.pos
    reached = math.hypot(here[0] - goal[0], here[1] - goal[1]) < 0.15 and w.level() == floor
    final = gl.message(w.t, everything=True)
    start = w.trace[0]
    route = find_route(final, [], cell(start[1], start[2], start[3] - 0.075), cell(here[0], here[1], w.floor_z))
    ks = [c[2] for c in route.get("cells", [])]
    rec("summary", floor=floor, reached=reached, final_pos=[round(float(v), 3) for v in here], final_level=w.level(),
        max_jump=round(max_jump(w.trace), 4), route=route["status"], route_k=[max(ks), min(ks)] if ks else None,
        seed=seed)
    path = out_dir / f"{floor.lower()}-{seed}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in records)
    verdict = evaluate(records)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": round(w.t, 2), "kind": "verdict", **verdict, "seed": seed}) + "\n")
    return verdict, path


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--max-t", type=float, default=500.0, help="sim seconds allowed")
    p.add_argument("--floor", choices=sorted(PATHS), default=FLOOR, help="target basement (default B2)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    verdict, path = run(args.seed, args.max_t, verbose=args.verbose, floor=args.floor)
    print(f"e2e-{args.floor.lower()} seed {args.seed} (casualty {CASUALTY[args.floor]}): {len(verdict['passed'])}/{len(STEPS)} steps passed")
    for name in STEPS:
        s = verdict["steps"][name]
        t = f"{s['t']:6.1f}s" if isinstance(s["t"], (int, float)) else "       "
        print(f"  {'ok  ' if s['ok'] else 'FAIL'} {t}  {name}: {s['detail']}")
    print(f"log: {path}")
    return 0 if not verdict["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
