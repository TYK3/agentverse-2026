"""L4 proof: the Scout finds its own way from L1 down to a basement (B1, B2 or B3) in the real sim,
no teleport.

    python -m sim.demo_descent            # L1 -> B1, prints each re-plan and the result
    python -m sim.demo_descent B2         # L1 -> B2 (b2: ground -> B1 on R1, then B1 -> B2 on R3)
    python -m sim.demo_descent B3         # L1 -> B3 (b3: then B2 -> B3 on R4)
    python -m sim.demo_descent B3 --shift # B3-SHIFT: a slab shifts as the Scout reaches B2

Loop: the sim ticks at 10 Hz (sim.levels.LevelWorld: height only from the floor under the Scout);
every sensors/scout frame updates the multi-level map (perception.levels); whenever the Scout stops,
the multi-level A* (planner.levels) plans from where it stands to the goal. A route it can walk
gives the next waypoint; an unknown goal gives the frontier closest to it in 3D; a frontier under
the Scout's feet (a ramp the 2D LiDAR cannot map) gives a short probe step into the unknown, which
the sim's floor check accepts or refuses. Nothing is scripted: no waypoint, ramp or level is given.

B3-SHIFT: run(floor="B3", shift_on="B2") drops a slab chunk onto B2 (LevelWorld.shift_slab) the first
time the Scout stands on B2. The Scout stops; the loop then does a fresh recheck before it plans again:
it forgets every map cell within RECHECK_R of the Scout on its floor (what it saw there was seen before
the shift), waits out the sim's SETTLE, and scans RECHECK_FRAMES times standing still. Only then does it
re-plan, on what it sees now.

run() returns a summary the tests check: reached the goal on its level, levels visited in order, the
largest move per tick (no teleport), and a Responder route over the finished map from L1 to the goal.
"""

import math

from perception.levels import GridLevels, k_of
from planner.levels import NEIGHBOURS, find_route, waypoints
from sim.levels import LEVEL_Z, LevelWorld, max_jump

RES = 0.05
GOALS = {
    "B1": (0.75, 1.55, -0.6),   # beside casualty c1 in B1 (sim/scenes/levels.xml)
    "B2": (0.75, 0.8, -1.2),    # beside casualty c2 in B2
    "B3": (0.75, 1.6, -1.8),    # beside casualty c3 in B3
}
GOAL = GOALS["B1"]
DT = 0.1
SCAN_EVERY = 3                   # map every 3rd frame while driving, every frame when stopped
PROBE = 0.15                     # metres stepped into the unknown
RECHECK_R = 2.0                  # metres around the Scout forgotten on its floor after a slab shift
RECHECK_FRAMES = 5               # standing-still scans after the shift has settled, before re-planning


def cell(x, y, z):
    return [math.floor(x / RES), math.floor(y / RES), k_of(z)]


def probe_target(world, frontier, goal_cell, levels):
    """(target point PROBE from the Scout toward the frontier's unknown neighbour closest to the
    goal, that neighbour cell), or None if the frontier has no unknown neighbour."""
    i, j, k = frontier
    best = None
    for dx, dy in NEIGHBOURS:
        col = levels.cols.get((i + dx, j + dy)) or {}
        if any(abs(kk - k) <= 1 for kk in col):
            continue
        n = (i + dx, j + dy, k)
        d = levels.dist(n, tuple(goal_cell))
        if best is None or d < best[0]:
            best = (d, dx, dy, n)
    if best is None:
        return None
    _, dx, dy, n = best
    norm = math.hypot(dx, dy)
    x, y = world.pos[:2]
    return [float(x + dx / norm * PROBE), float(y + dy / norm * PROBE), float(world.floor_z)], n


def forget_around(gl, xy, k, radius=RECHECK_R):
    """Drop every map cell within radius of xy on floor k (LiDAR, refused and trail), so that floor is
    mapped again from fresh looks. Ramp cells (other k) stay: only driving the ramp again could
    re-measure them, and a 2D LiDAR on flat floor writes only at its own k. Returns the count."""
    dropped = 0
    for c in list(gl.cells):
        i, j, kk = c
        if kk == k and math.hypot((i + 0.5) * RES - xy[0], (j + 0.5) * RES - xy[1]) <= radius:
            if gl.cells[c]["source"] == "trail":
                gl.trail.pop((i, j), None)
            gl._drop(c)
            dropped += 1
    return dropped


def run(max_t=600.0, verbose=False, floor="B1", shift_on=None):
    from planner.levels import Levels

    goal = GOALS[floor]

    w = LevelWorld(render=False)
    gl = GridLevels(RES)
    goal_cell = cell(*goal)
    visited = [w.level()]
    plans = 0
    frame = 0
    log = []
    probing = None              # the unknown cell the last probe stepped toward
    shift = None                # B3-SHIFT record, once the slab has shifted
    recheck = 0                 # standing-still scans still owed after the shift settles
    changes = []                # world/change payloads the sim published

    def say(msg):
        log.append(f"{w.t:6.1f}s {w.level():6s} {msg}")
        if verbose:
            print(log[-1])

    while w.t < max_t:
        if shift is not None and (w.settling() or recheck > 0):
            gl.add_sensors(w.sensors_message(camera=False))    # fresh looks only; no plan, no goto
            shift["held"].append(tuple(float(v) for v in w.pos))
            if not w.settling():
                recheck -= 1
                if recheck == 0:
                    say(f"recheck done after {len(shift['held'])} still scans")
            changes += [d for topic, d in w.tick(DT) if topic == "world/change"]
            continue
        stopped = w.state != "moving"
        frame += 1
        if stopped or frame % SCAN_EVERY == 0:
            gl.add_sensors(w.sensors_message(camera=False))
        if stopped:
            here = w.pos
            if math.hypot(here[0] - goal[0], here[1] - goal[1]) < 0.15 and w.level() == floor:
                break
            if probing is not None and w.state == "blocked" and cell(*here[:2], w.floor_z)[:2] != list(probing[:2]):
                gl.refuse(probing)      # the sim refused the step: that cell is not drivable
            probing = None
            snapshot = gl.message(w.t, everything=True)
            plan = find_route(snapshot, [], cell(here[0], here[1], w.floor_z), goal_cell)
            plans += 1
            if shift is not None:
                shift["plans"].append(plan.get("cells", []))
            if plan["status"] == "ok":
                wps = waypoints(plan["cells"], RES)
                target, why = wps[0] if len(wps) == 1 or _near(here, wps[0]) is False else wps[1], "route"
            elif plan["status"] == "explore":
                wps = waypoints(plan["cells"], RES)
                if len(plan["cells"]) > 2:
                    target, why = wps[0] if not _near(here, wps[0]) else wps[min(1, len(wps) - 1)], "explore"
                else:
                    probe = probe_target(w, plan["frontier"], goal_cell, Levels(snapshot))
                    target, why = (probe[0] if probe else None), "probe"
                    probing = probe[1] if probe else None
            else:
                say(f"stuck: {plan.get('reason')}")
                break
            if target is None:
                say("stuck: no probe direction")
                break
            say(f"{why} -> {[round(v, 2) for v in target]} ({w.state})")
            w.goto({"target": target, "reason": f"L4 {why}"})
        changes += [d for topic, d in w.tick(DT) if topic == "world/change"]
        if w.level() not in ("ramp", visited[-1]):
            visited.append(w.level())
        if shift_on and shift is None and abs(w.floor_z - LEVEL_Z[shift_on]) < 0.005:   # off the ramp, on it
            w.shift_slab()
            k = k_of(w.floor_z)
            shift = {"t": round(w.t, 2), "pos": tuple(float(v) for v in w.pos), "state": w.state,
                     "forgot": forget_around(gl, w.pos[:2], k), "held": [], "plans": []}
            recheck = RECHECK_FRAMES
            say(f"slab shift: stop, forgot {shift['forgot']} cells within {RECHECK_R} m, recheck")

    here = w.pos
    reached = math.hypot(here[0] - goal[0], here[1] - goal[1]) < 0.15 and w.level() == floor
    final = gl.message(w.t, everything=True)
    start = w.trace[0]
    # The Responder's route: from the Scout's start on L1 to where the Scout stopped by the casualty, over
    # the map the Scout built (the goal cell itself is in keep-out of the casualty marker).
    responder = find_route(final, [], cell(start[1], start[2], start[3] - 0.075),
                           cell(here[0], here[1], w.floor_z))
    ks = [c[2] for c in responder.get("cells", [])]
    return {
        "reached": reached, "t": round(w.t, 1), "levels": visited, "plans": plans,
        "max_jump": round(max_jump(w.trace), 4), "final_pos": [round(float(v), 3) for v in here],
        "responder_route": responder["status"], "route_k": (max(ks), min(ks)) if ks else None,
        "map_levels": gl.levels(), "log": log, "map": final,
        "start_cell": cell(start[1], start[2], start[3] - 0.075), "goal_cell": goal_cell,
        "trail": [cell(x, y, z - 0.075) for _, x, y, z in w.trace[::10]],
        "trace": [tuple(float(v) for v in row) for row in w.trace],   # (t, x, y, z) every tick
        "shift": shift, "world_change": changes,
    }


def _near(pos, wp, tol=0.05):
    return math.hypot(pos[0] - wp[0], pos[1] - wp[1]) < tol and abs(pos[2] - 0.075 - wp[2]) < 0.1


if __name__ == "__main__":
    import sys

    args = [a for a in sys.argv[1:] if a != "--shift"]
    out = run(verbose=True, floor=args[0] if args else "B1", shift_on="B2" if "--shift" in sys.argv else None)
    for key in ("log", "map", "trail", "trace", "shift"):
        out.pop(key)
    print(out)
