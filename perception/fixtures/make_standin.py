"""Write a STAND-IN sensors/scout recording until sim's T04 recording lands.

    uv run --no-project --with mujoco --with numpy python perception/fixtures/make_standin.py

Ray-casts the backup scene the way the T04 sketch does (360 horizontal rays, 6 m, scene frame) from
a scripted path: in through the south breach, room 1, the doorway, room 2, the gap past b11, room 3.
LiDAR only, at 10 Hz and 0.3 m/s; no camera, thermal or acoustic.
"""

import itertools
import json
import pathlib

import mujoco
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCENE = ROOT / "sim" / "scenes" / "backup.xml"
OUT = pathlib.Path(__file__).parent / "scout_backup_standin.jsonl"

Z = 0.075             # LiDAR height: grid layer k = 1
SPEED, HZ = 0.3, 10
PATH = [(-0.5, -1.4), (-0.5, -0.3), (-0.8, 0.25), (0.6, 0.25), (0.9, 0.75), (1.6, 0.75), (1.75, 0.3)]


def lidar(m, d, origin, n=360, max_range=6.0):
    ranges = np.full(n, max_range)
    geomid = np.zeros(1, dtype=np.int32)
    for k in range(n):
        a = 2 * np.pi * k / n
        vec = np.array([np.cos(a), np.sin(a), 0.0])
        dist = mujoco.mj_ray(m, d, origin, vec, None, 1, -1, geomid)
        if dist >= 0:
            ranges[k] = min(dist, max_range)
    return ranges


def poses():
    step = SPEED / HZ
    for (x0, y0), (x1, y1) in itertools.pairwise(PATH):
        length = np.hypot(x1 - x0, y1 - y0)
        yaw = float(np.arctan2(y1 - y0, x1 - x0))
        for s in np.arange(0.0, length, step):
            yield [x0 + (x1 - x0) * s / length, y0 + (y1 - y0) * s / length, Z], yaw


def main():
    m = mujoco.MjModel.from_xml_path(str(SCENE))
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    with open(OUT, "w") as f:
        for n, (pos, yaw) in enumerate(poses()):
            data = {
                "t": round(n / HZ, 2),
                "pose": {"pos": [round(v, 3) for v in pos], "yaw": round(yaw, 3)},
                "lidar": [round(float(r), 3) for r in lidar(m, d, np.array(pos))],
            }
            f.write(json.dumps({"t": data["t"], "topic": "sensors/scout", "data": data}, separators=(",", ":")) + "\n")
    print(f"wrote {n + 1} frames to {OUT}")


if __name__ == "__main__":
    main()
