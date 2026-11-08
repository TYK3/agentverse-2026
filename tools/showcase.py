"""showcase: a fully preset rescue demo. No perception, no planner, no Gemini reasoning: every coordinate,
timing, line and reaction comes from tools/showcase_preset.json, so it runs the same way every time.

    python tools/showcase.py                      # MuJoCo viewer, real time, voice printed as text
    python tools/showcase.py --headless           # no window, fast (smoke test)
    GEMINI_MODE=live python tools/showcase.py     # same run; robot lines also spoken with Gemini TTS

Story (backup scene, upgraded at start):
  1. Scout is summoned and sweeps a preset survey path room by room; it finds casualty c1.
  2. EMERGENCY: aftershock. The room 1 corridor collapses onto route r1; the Responder switches to detour r1b.
  3. Responder deploys with water, first aid kit, bandage and blanket.
  4. Predicted sudden fall: b11 drops into the gap beside the casualty; the Responder holds and waits it out.
  5. The arm lifts b11 off the path; the Responder drives up to the casualty.
  6. It talks to the casualty and reads the wounds (preset triage).
  7. The arm sets down the supplies; first aid guidance is spoken.
  8. The signal model pings the casualty's location for human responders (operator approval required).
"""

import argparse
import json
import math
import os
import pathlib
import sys
import time

import mujoco

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim import responder as R
from sim import scene
from sim.world import World
from voice import emergency, firstaid, speak

PRESET_PATH = pathlib.Path(__file__).with_name("showcase_preset.json")
T0 = time.monotonic()


def log(tag, text):
    print(f"[{time.monotonic() - T0:6.1f}s] {tag:<10} {text}", flush=True)


def banner(text):
    print(f"\n=== {text} " + "=" * max(0, 72 - len(text)), flush=True)


class Show:
    def __init__(self, preset, viewer=None, realtime=False):
        self.p = preset
        self.dt = preset["dt"]
        self.res = preset["cell_res"]
        self.w = World(path=scene.NAMED[preset["scene"]], render=False)
        self.r = R.Responder(self.w.m, self.w.d, clock=lambda: self.w.t)
        self.v = viewer
        self.realtime = realtime
        self.mapped = set()
        self.ok = []          # (step, passed)

    # ---- plumbing -------------------------------------------------------------------------------------------
    def tick(self, n=1):
        for _ in range(n):
            t = time.monotonic()
            self.r.step(self.dt)
            self.w.tick(self.dt)
            if self.v is not None:
                self.v.sync()
            if self.realtime:
                time.sleep(max(0.0, self.dt - (time.monotonic() - t)))

    def wait(self, seconds):
        self.tick(max(1, round(seconds / self.dt)))

    def place(self, name, xyz):
        """Teleport free body `name` to xyz at rest, colliding (preset map upgrade and falls)."""
        m, d = self.w.m, self.w.d
        b = m.body(name).id
        j = m.body_jntadr[b]
        adr, vadr = m.jnt_qposadr[j], m.jnt_dofadr[j]
        m.body_gravcomp[b] = 0
        for g in range(m.body_geomadr[b], m.body_geomadr[b] + m.body_geomnum[b]):
            m.geom_contype[g], m.geom_conaffinity[g] = 1, 3
        m.body_contype[b], m.body_conaffinity[b] = 1, 3
        d.qpos[adr:adr + 7] = [*xyz, 1, 0, 0, 0]
        d.qvel[vadr:vadr + 6] = 0
        mujoco.mj_forward(m, d)

    def xy(self, name):
        p = self.w.d.xpos[self.w.m.body(name).id]
        return float(p[0]), float(p[1])

    def last(self):
        e = self.r.log[-1] if self.r.log else {"outcome": "?", "reason": ""}
        return e["outcome"], f"{e['outcome']}: {e['reason']}"

    def check(self, step, passed):
        self.ok.append((step, bool(passed)))

    def drive(self, rid, limit_s=120.0):
        self.r.on_route({"id": rid, "robot": "responder", "cells": R.cells_along(self.p["routes"][rid]),
                         "goal": "deliver supplies to c1", "model": "preset"})
        self.r.on_action({"action": "move", "route": rid, "item": self.p["supplies"]["carry_first"]})
        for _ in range(int(limit_s / self.dt)):
            self.tick()
            if self.r.state != "moving":
                break
        return self.r.state

    # ---- 0. map upgrade ---------------------------------------------------------------------------------------
    def upgrade_map(self):
        banner("0. MAP UPGRADE (preset)")
        up = self.p["map_upgrade"]
        for name, xyz in up["stash"].items():
            self.place(name, xyz)
            log("map", f"{name} staged off-stage at {xyz[:2]} (falls later)")
        for name, xyz in up["dressing"].items():
            self.place(name, xyz)
            log("map", f"{name} moved to {xyz[:2]}")
        self.w._set_pose(self.p["scout"]["park"], 0.0)
        self.wait(1.0)
        log("plan", "preset timeline: scout survey -> aftershock -> r1b detour -> b11 fall -> lift -> "
                    "talk -> treat -> ping")

    # ---- 1 + 2. scout mapping and the emergency -----------------------------------------------------------------
    def map_with_scout(self):
        banner("1. SCOUT SUMMONED: mapping")
        sc = self.p["scout"]
        path = sc["survey"]
        self.w._set_pose(path[0], math.pi / 2)
        for i in range(1, len(path)):
            a, b = path[i - 1], path[i]
            yaw = math.atan2(b[1] - a[1], b[0] - a[0])
            n = sc["steps_per_leg"]
            for s in range(1, n + 1):
                x, y = a[0] + (b[0] - a[0]) * s / n, a[1] + (b[1] - a[1]) * s / n
                self.w._set_pose((x, y), yaw)
                cx, cy = round(x / self.res), round(y / self.res)
                self.mapped.update((cx + dx, cy + dy) for dx in range(-8, 9) for dy in range(-8, 9))
                self.tick()
            room = sc["rooms"].get(str(i))
            log("scout", f"waypoint {i:2d}/{len(path) - 1} ({b[0]:+.2f}, {b[1]:+.2f})  "
                         f"{len(self.mapped):5d} cells mapped" + (f"  entering {room}" if room else ""))
            if i == sc["casualty_found_at_waypoint"]:
                cx, cy = self.xy("casualty_c1")
                log("scout", f"CASUALTY c1 at ({cx:.2f}, {cy:.2f}): thermal + voice, confidence "
                             f"{self.p['signal']['confidence']}")
                self.check("casualty found", True)
            if i == sc["emergency_at_waypoint"]:
                self.emergency()
        self.w._set_pose(sc["park"], 0.0)
        log("scout", f"survey done, parked at {sc['park']}")
        self.wait(0.5)

    def emergency(self):
        banner("2. EMERGENCY: aftershock, map changed")
        em = self.p["emergency"]
        if em["shake"]:
            self.w.trigger_aftershock()
            log("sim", "aftershock: ground shaking")
        for name, xyz in em["drops"].items():
            self.place(name, xyz)
            log("sim", f"{name} falls toward ({xyz[0]:+.2f}, {xyz[1]:+.2f})")
        while self.w.shaking:
            self.tick()
        self.wait(1.5)
        for name in em["drops"]:
            x, y = self.xy(name)
            log("scout", f"re-mapped: {name} now at ({x:+.2f}, {y:+.2f})")
        log("planner", f"map v2: route {em['blocked_route']} blocked in room 1; switching to preset detour "
                       f"{em['detour']}")
        self.check("map changed", True)

    # ---- 3-5. responder --------------------------------------------------------------------------------------
    def deploy(self):
        banner("3. RESPONDER DEPLOYED: water, first aid kit, bandage, blanket")
        detour = self.p["emergency"]["detour"]
        state = self.drive(detour)
        log("responder", f"route {detour}: {state} at {self.r.status()['pos']}  ({self.last()[1]})")
        self.check(f"arrived via {detour}", state == "arrived")
        self.wait(1.0)

        fall = self.p["sudden_fall"]
        banner("4. SUDDEN FALL (predicted)")
        log("planner", f"known risk: {fall['body']} over the room 2/3 gap at {fall['at'][:2]}; holding before the gap")
        self.place(fall["body"], fall["at"])
        log("sim", f"{fall['body']} falls at ({fall['at'][0]:+.2f}, {fall['at'][1]:+.2f})")
        log("responder", f"expected event: holding {fall['hold_s']} s for it to settle")
        self.wait(fall["hold_s"])
        x, y = self.xy(fall["body"])
        log("scout", f"{fall['body']} settled at ({x:+.2f}, {y:+.2f}): blocks r2 beside the casualty")
        self.check("fall handled", True)

        banner("5. ARM REMOVES THE DEBRIS")
        self.r.grip_block(fall["body"])
        out, text = self.last()
        log("arm", f"grip {fall['body']} -> {text}")
        self.check("debris lifted", out == "done")
        self.wait(1.0)
        state = self.drive("r2", limit_s=60)
        log("responder", f"route r2: {state} at {self.r.status()['pos']}, beside casualty c1")
        self.check("reached casualty", state == "arrived")
        self.wait(1.0)

    # ---- 6-7. talk and treat --------------------------------------------------------------------------------
    def talk_and_treat(self):
        banner("6. TALKING TO THE CASUALTY")
        for turn in self.p["conversation"]:
            speak.speak_text(turn["robot"], to="casualty")
            self.wait(0.5)
            log("casualty", turn["casualty"])
            self.wait(0.5)
        a = self.p["assessment"]
        log("triage", f"wounds identified ({a['source']}):")
        for w in a["wounds"]:
            log("wound", f"[{w['severity']:<6}] {w['where']}: {w['what']}")
        speak.speak_text(a["reply"], to="casualty")

        banner("7. FIRST AID: supplies set down, guidance spoken")
        placed = 0
        for item in self.p["supplies"]["set_down"]:
            if item == self.p["supplies"]["carry_first"]:
                self.r.on_action({"action": "place_supply", "route": "r2", "item": item})
            else:
                self.r.place_supply(item)
            out, text = self.last()
            placed += out == "done"
            log("arm", f"{item:<16} -> {text}")
            self.wait(0.8)
        self.check("supplies placed", placed == len(self.p["supplies"]["set_down"]))
        self.r.release_block(self.p["sudden_fall"]["body"])
        log("arm", f"set debris aside -> {self.last()[1]}")
        self.wait(0.8)
        for action in self.p["first_aid"]:
            step = firstaid.get_step(action)
            if step:
                speak.speak_text(firstaid.format_guidance(step), to="casualty")
                self.wait(0.5)

    # ---- 8. signal -------------------------------------------------------------------------------------------
    def ping(self):
        banner("8. SIGNAL MODEL: pinging casualty location")
        sg = self.p["signal"]
        x, y = self.xy("casualty_c1")
        cell = [int(x / self.res), int(y / self.res), 0]
        cas = {"id": sg["casualty_id"], "pos": [round(x, 2), round(y, 2), 0.0], "confidence": sg["confidence"],
               "clues": sg["clues"], "vitals": sg["vitals"]}
        log("signal", emergency.prepare_emergency_text(cas, cell=cell))
        for k in range(sg["beacon_pings"]):
            log("signal", f"PING {k + 1}: {sg['casualty_id']} ({sg['name']}) @ ({x:.2f}, {y:.2f}) cell {cell}, "
                          f"supplies on site")
            self.wait(sg["beacon_every_s"])
        self.check("location pinged", True)

    def run(self):
        self.upgrade_map()
        self.map_with_scout()
        self.deploy()
        self.talk_and_treat()
        self.ping()
        banner("RESULT")
        for step, passed in self.ok:
            print(f"  {'PASS' if passed else 'FAIL'}  {step}")
        print("  responder:", self.r.status())
        return all(p for _, p in self.ok)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--headless", action="store_true", help="no viewer window, run as fast as possible")
    ap.add_argument("--preset", default=str(PRESET_PATH))
    args = ap.parse_args()
    preset = json.loads(pathlib.Path(args.preset).read_text(encoding="utf-8"))
    log("mode", f"preset {pathlib.Path(args.preset).name}; GEMINI_MODE={os.environ.get('GEMINI_MODE', 'off')} "
                f"(TTS only, no reasoning calls)")
    show = Show(preset)
    if args.headless:
        sys.exit(0 if show.run() else 1)
    import mujoco.viewer
    with mujoco.viewer.launch_passive(show.w.m, show.w.d) as v:
        show.v, show.realtime = v, True
        show.run()
        print("\nDone. Close the viewer window to exit.")
        while v.is_running():
            time.sleep(0.1)


if __name__ == "__main__":
    main()
