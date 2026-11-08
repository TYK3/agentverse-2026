"""Scripted Responder run (T06): drive in, clear light debris b11, deliver water to casualty c1, release.

Run:  python -m sim.demo_responder              (MuJoCo viewer window, real time)
      python -m sim.demo_responder --headless   (no window, as fast as possible; prints the log)

The routes are hand-written cell lists here; in the full system they come from the planner as
route/proposed and the actions as responder/action (see sim/responder.py).
"""

import argparse
import time

from sim import responder as R
from sim.world import World

DT = 0.1
# (x, y) corners in the scene frame; cells_along() turns them into 5 cm route cells at layer k=0.
ROUTES = {
    # through the breach beside the rubble pile, across room 1, through the doorway, up to block b11
    "r1": [(-0.48, -1.77), (-0.48, 0.25), (0.97, 0.25), (0.97, 0.47)],
    # through the room 2/3 gap that b11 was blocking, then up to casualty c1
    "r2": [(0.97, 0.47), (1.77, 0.47), (1.77, 0.62)],
}
SCRIPT = [
    ("route", "r1"), ("move", "r1"),
    ("grip_block", "b11"),
    ("route", "r2"), ("move", "r2"),
    ("place_supply", "water"),
    ("release_block", "b11"),
]


def run(world=None, responder=None, on_step=None, realtime=False):
    """Play SCRIPT; returns (world, responder). `on_step(world, responder)` runs after every tick."""
    world = world or World(render=False)
    world._set_pose((-1.2, -1.7), 0.0)          # park the Scout beside the breach, out of the Responder's way
    r = responder or R.Responder(world.m, world.d, clock=lambda: world.t)

    def tick():
        started = time.monotonic()
        r.step(DT)
        world.tick(DT)
        if on_step:
            on_step(world, r)
        if realtime:
            time.sleep(max(0.0, DT - (time.monotonic() - started)))

    for _ in range(5):                          # let the scene settle
        tick()
    for kind, arg in SCRIPT:
        if kind == "route":
            r.on_route({"id": arg, "robot": "responder", "cells": R.cells_along(ROUTES[arg]),
                        "goal": "deliver water to c1", "model": "local-astar"})
        elif kind == "move":
            r.on_action({"action": "move", "route": arg, "item": "water"})
            for _ in range(int(120 / DT)):
                tick()
                if r.state != "moving":
                    break
        elif kind == "place_supply":
            r.on_action({"action": "place_supply", "route": "r2", "item": arg})
        else:
            getattr(r, kind)(arg)
        for _ in range(10):                     # one second for the physics to settle after each action
            tick()
    return world, r


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--headless", action="store_true", help="no viewer window")
    args = ap.parse_args()
    world = World(render=False)
    if args.headless:
        _, r = run(world)
    else:
        import mujoco.viewer

        with mujoco.viewer.launch_passive(world.m, world.d) as v:
            _, r = run(world, on_step=lambda w, _r: v.sync(), realtime=True)
            print("Done. Close the viewer window to exit.")
            while v.is_running():
                time.sleep(0.1)
    for entry in r.log:
        print(f"t={entry['t']:6.1f}  {entry['outcome']:8s} {entry['reason']}")
    print("final:", r.status())


if __name__ == "__main__":
    main()
