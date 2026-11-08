"""LEVELS-LIVE-2: save the Scout's RGB-D at each B1 / B2 / B3 stop of the real chained run (tools/run_levels.py).

    MUJOCO_GL=egl GEMINI_MODE=off python tools/levels_frames.py        # runs/levels-<seed>-frames/

Runs tools/run_levels.run unchanged; only the world it builds is a FrameWorld (a sim.levels.LevelWorld that
also owns an offscreen renderer). The run's loop asks for sensors every frame while the Scout is stopped and
then checks "at the goal"; FrameWorld takes the frame on that same call, on the same state: stopped (not
moving) on B1/B2/B3 within run_levels.NEAR of that floor's goal, once per floor. So a frame is a real stop
at the casualty, from the Scout's own camera, never a staged camera.

Per floor it writes <floor>_rgb.png (8-bit RGB), <floor>_depth.png (16-bit, millimetres; 0 = no return or sky)
and one frames.json with t, floor, the Scout pose, camera, image size, depth range and the files. With no
GL context (CI, or MUJOCO_GL unset on a headless box) the stops are still listed with "rgbd": null and the
reason, so a missing frame is visible rather than silent. The run log goes next to it as levels-<seed>.jsonl.
"""

import argparse
import json
import math
import pathlib
import sys
from unittest import mock

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import run_levels

FLOORS = run_levels.LEGS            # ("B1", "B2", "B3")
DEPTH_SCALE = 1000.0                # metres -> millimetres in the 16-bit PNG
NO_GL = "no GL renderer (headless without MUJOCO_GL=egl or osmesa)"


def at_stop(state, level, pos, goals, done, near=run_levels.NEAR):
    """The floor to capture now, or None: stopped, on a floor in FLOORS, within `near` of its goal, first time."""
    if state == "moving" or level not in FLOORS or level in done:
        return None
    gx, gy = goals[level][:2]
    return level if math.hypot(pos[0] - gx, pos[1] - gy) < near else None


def depth_png(depth_m, far=None):
    """Depth in metres -> uint16 millimetres; non-finite, <= 0 or at the far clip (sky) -> 0 (no return)."""
    d = np.asarray(depth_m, dtype=np.float64)
    ok = np.isfinite(d) & (d > 0)
    if far is not None:
        ok &= d < 0.999 * far
    mm = np.where(ok, np.round(d * DEPTH_SCALE), 0)
    return np.clip(mm, 0, np.iinfo(np.uint16).max).astype(np.uint16)


def save_rgbd(out_dir, floor, rgb, depth_m, far=None):
    """Write <floor>_rgb.png and <floor>_depth.png; return the file names and the depth range in metres."""
    from PIL import Image

    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rgb_name, depth_name = f"{floor}_rgb.png", f"{floor}_depth.png"
    Image.fromarray(np.asarray(rgb, dtype=np.uint8)).save(out_dir / rgb_name)
    mm = depth_png(depth_m, far)
    Image.fromarray(mm).save(out_dir / depth_name)
    valid = mm[mm > 0] / DEPTH_SCALE
    rng = [round(float(valid.min()), 3), round(float(np.median(valid)), 3), round(float(valid.max()), 3)] \
        if valid.size else None
    return {"rgb": rgb_name, "depth": depth_name, "depth_units": "mm", "depth_min_median_max_m": rng}


def frame_world(out_dir, goals):
    """A LevelWorld subclass that saves RGB-D at each floor's stop into out_dir (built lazily: sim imports)."""
    from sim import sensors
    from sim.levels import LevelWorld

    class FrameWorld(LevelWorld):
        def __init__(self, *args, render=False, **kwargs):
            super().__init__(*args, render=render, **kwargs)
            self.frame_renderer = sensors.make_renderer(self.m)
            self.frames = []
            self._done = set()

        def capture(self, floor):
            """Render the Scout camera now (RGB and depth) and record it."""
            pos = [round(float(v), 3) for v in self.pos]
            entry = {"t": round(float(self.t), 1), "floor": floor, "level": self.level(), "pos": pos,
                     "yaw": round(float(self.yaw), 3), "state": self.state, "camera": self.camera_name}
            r = self.frame_renderer
            if r is None:
                entry.update(rgbd=None, reason=NO_GL)
            else:
                r.update_scene(self.d, camera=self.camera_name)
                rgb = r.render().copy()
                r.enable_depth_rendering()
                r.update_scene(self.d, camera=self.camera_name)
                depth = r.render().copy()
                r.disable_depth_rendering()
                far = float(self.m.vis.map.zfar * self.m.stat.extent)     # MuJoCo's far clip, metres
                entry.update(width=int(rgb.shape[1]), height=int(rgb.shape[0]),
                             fovy=float(self.m.cam_fovy[self.m.camera(self.camera_name).id]),
                             far_m=round(far, 3), rgbd=save_rgbd(out_dir, floor, rgb, depth, far))
            self.frames.append(entry)
            self._done.add(floor)
            return entry

        def sensors_message(self, camera=True):
            msg = super().sensors_message(camera=camera)
            floor = at_stop(self.state, self.level(), self.pos, goals, self._done)
            if floor is not None:
                self.capture(floor)
            return msg

    return FrameWorld


def run(seed=0, max_t=900.0, out_dir=None, verbose=False):
    """The real chained run with a frame at each B1/B2/B3 stop; returns (records, frames)."""
    from sim import demo_descent as dd
    from sim import levels as sim_levels

    out_dir = pathlib.Path(out_dir or ROOT / "runs" / f"levels-{seed}-frames")
    world = frame_world(out_dir, dd.GOALS)
    made = []

    def build(*args, **kwargs):
        w = world(*args, **kwargs)
        made.append(w)
        return w

    with mock.patch.object(sim_levels, "LevelWorld", build):
        records = run_levels.run(seed, max_t, verbose)
    frames = made[0].frames if made else []
    write_outputs(out_dir, seed, records, frames)
    return records, frames


def write_outputs(out_dir, seed, records, frames):
    """The run log (levels-<seed>.jsonl, as run_levels writes it) and frames.json, into out_dir."""
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"levels-{seed}.jsonl").write_text("".join(json.dumps(r, separators=(",", ":")) + "\n"
                                                          for r in records))
    (out_dir / "frames.json").write_text(json.dumps({"seed": seed, "source": "tools/levels_frames.py",
                                                     "frames": frames}, indent=1) + "\n")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--max-t", type=float, default=900.0)
    p.add_argument("--out", default=None, help="default runs/levels-<seed>-frames/")
    a = p.parse_args(argv)
    records, frames = run(a.seed, a.max_t, a.out)
    verdict = run_levels.evaluate(records)
    reached = [r["floor"] for r in records if r["kind"] == "leg" and r["reached"]]
    for f in frames:
        what = f"{f['rgbd']['rgb']} + {f['rgbd']['depth']} depth {f['rgbd']['depth_min_median_max_m']} m" \
            if f["rgbd"] else f["reason"]
        print(f"  {f['floor']} t={f['t']}s at {f['pos']}: {what}")
    missing = [fl for fl in reached if fl not in {f["floor"] for f in frames}]
    n = len(verdict["steps"])
    print(f"run {n - len(verdict['failed'])}/{n} steps; frames {len(frames)} for reached floors {reached}"
          + (f"; missing {missing}" if missing else ""))
    return 0 if not verdict["failed"] and not missing else 1


if __name__ == "__main__":
    sys.exit(main())
