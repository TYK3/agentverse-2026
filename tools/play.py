"""MuJoCo viewer on the levels (B1) building, and a live B1 rescue via --rescue (ref TESTBED-2).

    python tools/play.py                      # viewer on sim/scenes/levels.xml
    python tools/play.py --rescue             # Scout finds c1 in B1, then a Responder route
    python tools/play.py --rescue --no-viewer # same rescue, no window (CI / no DISPLAY)

`--rescue` uses the real closed loop from sim.demo_descent: LevelWorld physics, perception.levels
and planner.levels. Nothing is scripted and no bus message is faked. GEMINI_MODE defaults to off.

The levels scene has no Responder body and no supply kit, so a Responder route is planned over the
map the Scout built, and driving / place_supply run only when those bodies exist (as far as this
stack can go). tools/demo.py is the hub+console path, not a MuJoCo viewer.

Keys in the interactive viewer:
    S  slab shift (the live aftershock; levels.xml has no free blocks, so nothing falls)
    C  spawn a spare rubble block if the scene has one (World.add_block)
    R  reset the Scout and physics to the pose at launch
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DT = 0.1


def parse(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--rescue", action="store_true",
                   help="run the live B1 rescue: Scout finds c1, then plan (and drive if possible) a Responder route")
    p.add_argument("--no-viewer", "--headless", action="store_true", dest="no_viewer",
                   help="do not open a MuJoCo window")
    p.add_argument("--max-t", type=float, default=600.0, dest="max_t",
                   help="sim-seconds to wait for the Scout to reach B1 (default 600)")
    a = p.parse_args(argv)
    if a.max_t <= 0:
        p.error("--max-t must be positive")
    return a


def want_viewer(no_viewer, env=None):
    """False when the caller asked for headless, or this process has no display to open one on."""
    if no_viewer:
        return False
    env = os.environ if env is None else env
    if env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"):
        return True
    return sys.platform == "win32"


def _has_body(m, name):
    import mujoco
    return mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, name) >= 0


def snapshot(world):
    """Pose and World fields needed to put the scene back as it was at launch."""
    return {
        "qpos": world.d.qpos.copy(),
        "qvel": world.d.qvel.copy(),
        "mocap_pos": world.d.mocap_pos.copy(),
        "mocap_quat": world.d.mocap_quat.copy(),
        "eq_active": world.d.eq_active.copy(),
        "t": world.t,
        "target": None if world.target is None else world.target.copy(),
        "state": world.state,
        "reason": world.reason,
        "shake_t0": world.shake_t0,
        "shake_start": world.shake_start,
        "events": list(world.events),
        "landing": world.landing,
        "tapping": dict(world.tapping),
        "replies": list(world.replies),
        "floor_z": getattr(world, "floor_z", None),
        "target_z": getattr(world, "target_z", None),
        "trace": list(getattr(world, "trace", [])),
    }


def restore(world, snap):
    import mujoco
    world.d.qpos[:] = snap["qpos"]
    world.d.qvel[:] = snap["qvel"]
    world.d.mocap_pos[:] = snap["mocap_pos"]
    world.d.mocap_quat[:] = snap["mocap_quat"]
    world.d.eq_active[:] = snap["eq_active"]
    mujoco.mj_forward(world.m, world.d)
    world.t = snap["t"]
    world.target = None if snap["target"] is None else snap["target"].copy()
    world.state = snap["state"]
    world.reason = snap["reason"]
    world.shake_t0 = snap["shake_t0"]
    world.shake_start = snap["shake_start"]
    world.events = list(snap["events"])
    world.landing = snap["landing"]
    world.tapping = dict(snap["tapping"])
    world.replies = list(snap["replies"])
    if hasattr(world, "floor_z"):
        world.floor_z = snap["floor_z"]
        world.target_z = snap["target_z"]
        world.trace = list(snap["trace"])


class Controls:
    """Keyboard bindings for the idle viewer (slab shift, spare block, reset)."""

    def __init__(self, world):
        self.world = world
        self.snap = snapshot(world)

    def handle(self, key):
        if key in (ord("S"), ord("s")):
            if self.world.trigger_aftershock():
                print(f"t={self.world.t:.1f}s slab shift: aftershock started")
            else:
                print(f"t={self.world.t:.1f}s slab shift: an aftershock is already running")
        elif key in (ord("C"), ord("c")):
            z = getattr(self.world, "floor_z", 0.0) + 0.3
            name = self.world.add_block([float(self.world.pos[0] + 0.4), float(self.world.pos[1]), z])
            if name is None:
                print("spawn: this scene has no spare block (levels.xml already has casualties c1-c3)")
            else:
                print(f"t={self.world.t:.1f}s spawn: dropped spare block {name}")
        elif key in (ord("R"), ord("r")):
            restore(self.world, self.snap)
            print("reset: scene restored to the launch pose")


def _tick(world, on_step=None, realtime=False, extra=None):
    started = time.monotonic()
    if extra is not None:
        extra()
    world.tick(DT)
    if on_step:
        on_step(world)
    if realtime:
        time.sleep(max(0.0, DT - (time.monotonic() - started)))


def descend(world, on_step=None, realtime=False, max_t=600.0, floor="B1", verbose=False,
            should_continue=None):
    """Scout finds the casualty on `floor` using sim.demo_descent's real loop. Returns its summary."""
    import math

    from perception.levels import GridLevels
    from planner.levels import Levels, find_route, waypoints
    from sim.demo_descent import GOALS, SCAN_EVERY, _near, cell, probe_target
    from sim.levels import max_jump

    goal = GOALS[floor]
    gl = GridLevels()
    goal_cell = cell(*goal)
    visited = [world.level()]
    plans = 0
    frame = 0
    log = []
    probing = None

    def say(msg):
        log.append(f"{world.t:6.1f}s {world.level():6s} {msg}")
        if verbose:
            print(log[-1], flush=True)

    while world.t < max_t and (should_continue is None or should_continue()):
        stopped = world.state != "moving"
        frame += 1
        if stopped or frame % SCAN_EVERY == 0:
            gl.add_sensors(world.sensors_message(camera=False))
        if stopped:
            here = world.pos
            if math.hypot(here[0] - goal[0], here[1] - goal[1]) < 0.15 and world.level() == floor:
                break
            if probing is not None and world.state == "blocked" and cell(*here[:2], world.floor_z)[:2] != list(probing[:2]):
                gl.refuse(probing)
            probing = None
            snapshot_map = gl.message(world.t, everything=True)
            plan = find_route(snapshot_map, [], cell(here[0], here[1], world.floor_z), goal_cell)
            plans += 1
            if plan["status"] == "ok":
                wps = waypoints(plan["cells"])
                target, why = wps[0] if len(wps) == 1 or _near(here, wps[0]) is False else wps[1], "route"
            elif plan["status"] == "explore":
                wps = waypoints(plan["cells"])
                if len(plan["cells"]) > 2:
                    target, why = wps[0] if not _near(here, wps[0]) else wps[min(1, len(wps) - 1)], "explore"
                else:
                    probe = probe_target(world, plan["frontier"], goal_cell, Levels(snapshot_map))
                    target, why = (probe[0] if probe else None), "probe"
                    probing = probe[1] if probe else None
            else:
                say(f"stuck: {plan.get('reason')}")
                break
            if target is None:
                say("stuck: no probe direction")
                break
            say(f"{why} -> {[round(v, 2) for v in target]} ({world.state})")
            world.goto({"target": target, "reason": f"L4 {why}"})
        _tick(world, on_step, realtime)
        if world.level() not in ("ramp", visited[-1]):
            visited.append(world.level())

    here = world.pos
    reached = math.hypot(here[0] - goal[0], here[1] - goal[1]) < 0.15 and world.level() == floor
    final = gl.message(world.t, everything=True)
    start = world.trace[0]
    responder = find_route(final, [], cell(start[1], start[2], start[3] - 0.075),
                           cell(here[0], here[1], world.floor_z))
    ks = [c[2] for c in responder.get("cells", [])]
    return {
        "reached": reached, "t": round(world.t, 1), "levels": visited, "plans": plans,
        "max_jump": round(max_jump(world.trace), 4),
        "final_pos": [round(float(v), 3) for v in here],
        "responder_route": responder["status"],
        "route_k": (max(ks), min(ks)) if ks else None,
        "route_cells": responder.get("cells") or [],
        "map": final, "log": log,
        "start_cell": cell(start[1], start[2], start[3] - 0.075),
        "goal_cell": goal_cell,
    }


def drive_responder(world, route_cells, on_step=None, realtime=False, should_continue=None,
                    item="water"):
    """Follow `route_cells` with sim.responder.Responder and place a supply if the scene has that kit."""
    from sim import responder as R

    if not route_cells:
        return {"driven": False, "reason": "no responder cells to follow", "log": []}
    if not _has_body(world.m, "responder"):
        return {"driven": False,
                "reason": "levels scene has no responder body; route produced but not driven",
                "log": []}

    r = R.Responder(world.m, world.d, clock=lambda: world.t, shaking=lambda: world.shaking)
    r.on_route({"id": "rescue", "robot": "responder", "cells": route_cells,
                "goal": f"deliver {item} to c1", "model": "planner.levels"})
    r.on_action({"action": "move", "route": "rescue", "item": item})
    while r.state == "moving" and (should_continue is None or should_continue()):
        _tick(world, on_step, realtime, extra=lambda: r.step(DT))

    supply = None
    if r.state == "arrived":
        if r._eq("carry_" + item) < 0:
            supply = {"outcome": "skipped", "reason": f"{item} is not loaded in this scene's kit"}
        else:
            supply = r.on_action({"action": "place_supply", "route": "rescue", "item": item})
    return {"driven": True, "state": r.state, "status": r.status(), "supply": supply, "log": list(r.log)}


def run_rescue(world=None, on_step=None, realtime=False, max_t=600.0, floor="B1", verbose=False,
               should_continue=None):
    """Full B1 rescue on the levels scene, as far as the current stack can go."""
    from sim.levels import LevelWorld

    os.environ.setdefault("GEMINI_MODE", "off")
    world = world or LevelWorld(render=False)
    out = descend(world, on_step=on_step, realtime=realtime, max_t=max_t, floor=floor,
                  verbose=verbose, should_continue=should_continue)
    out["responder_drive"] = drive_responder(
        world, out["route_cells"], on_step=on_step, realtime=realtime,
        should_continue=should_continue)
    return out


def _summary(result):
    keys = ("reached", "t", "levels", "plans", "max_jump", "final_pos",
            "responder_route", "route_k", "responder_drive")
    out = {k: result[k] for k in keys if k in result}
    drive = out.get("responder_drive") or {}
    if drive.get("log"):
        out["responder_drive"] = {k: drive[k] for k in drive if k != "log"}
    return out


def open_viewer(world, key_callback=None):
    """Open a passive viewer, or return None if the window cannot be created."""
    try:
        import mujoco.viewer
        return mujoco.viewer.launch_passive(world.m, world.d, key_callback=key_callback)
    except (OSError, RuntimeError, ImportError) as exc:
        print(f"viewer could not open ({exc}); continuing headless", file=sys.stderr)
        return None


def play_idle(world, viewer, realtime=True):
    """Keep physics ticking so keys (aftershock, reset) have an effect, until the window closes."""
    idle_dt = 0.02
    while viewer.is_running():
        started = time.monotonic()
        world.tick(idle_dt)
        viewer.sync()
        if realtime:
            time.sleep(max(0.0, idle_dt - (time.monotonic() - started)))


def main(argv=None):
    os.environ.setdefault("GEMINI_MODE", "off")
    args = parse(argv)
    from sim.levels import LevelWorld

    world = LevelWorld(render=False)
    print(f"levels scene loaded; Scout on {world.level()} at "
          f"{[round(float(v), 3) for v in world.pos]}  GEMINI_MODE={os.environ.get('GEMINI_MODE')}")
    viewer = None
    controls = Controls(world)
    if want_viewer(args.no_viewer):
        viewer = open_viewer(world, key_callback=controls.handle)
        if viewer is not None:
            print("viewer: S slab shift, C spawn spare block, R reset  (close the window to exit)")
    elif not args.rescue:
        print("no viewer (--no-viewer or no DISPLAY). pass --rescue to run the B1 rescue headless.")
        return 0

    code = 0
    try:
        if args.rescue:
            should = (lambda: viewer.is_running()) if viewer is not None else None
            on_step = (lambda _w: viewer.sync()) if viewer is not None else None
            result = run_rescue(world, on_step=on_step, realtime=viewer is not None,
                                max_t=args.max_t, verbose=True, should_continue=should)
            print("result:", _summary(result), flush=True)
            if not result["reached"]:
                code = 1
            if viewer is not None:
                print("Done. Close the viewer window to exit.")
                play_idle(world, viewer)
        elif viewer is not None:
            play_idle(world, viewer)
    finally:
        if viewer is not None:
            viewer.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
