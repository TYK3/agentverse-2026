"""Simulated Scout sensors (T04): ray-cast LiDAR, camera, thermal grid, acoustic bearing.

Conventions (scene frame, metres, radians unless named _deg):
- LiDAR ray k points at angle 2*pi*k/n from world +x, counter-clockwise, horizontal, from the
  Scout origin. A miss reads max_range. The Scout's own body is excluded.
- Bearings are relative to the Scout heading, degrees in (-180, 180], positive to the left.
"""

import base64
import io

import mujoco
import numpy as np

MAX_RANGE = 6.0
THERMAL_W, THERMAL_H = 16, 12
THERMAL_FOV_H, THERMAL_FOV_V = np.radians(60.0), np.radians(45.0)
THERMAL_RANGE = 4.0


def _ray(m, d, origin, vec, exclude):
    geomid = np.zeros(1, dtype=np.int32)
    dist = mujoco.mj_ray(m, d, np.asarray(origin, float), np.asarray(vec, float), None, 1, exclude, geomid)
    return dist, int(geomid[0])


def lidar(m, d, origin, exclude_body, n=360, max_range=MAX_RANGE):
    """n horizontal ranges around `origin`, world-frame angles (see module docstring)."""
    ranges = np.full(n, max_range)
    for k in range(n):
        a = 2 * np.pi * k / n
        dist, _ = _ray(m, d, origin, [np.cos(a), np.sin(a), 0.0], exclude_body)
        if dist >= 0:
            ranges[k] = min(dist, max_range)
    return ranges


def first_hit(m, d, origin, target, exclude_body):
    """(geom id, distance) of the first geom on the segment origin->target, or (-1, length)."""
    delta = np.asarray(target, float) - np.asarray(origin, float)
    length = float(np.linalg.norm(delta))
    dist, geom = _ray(m, d, origin, delta / length, exclude_body)
    if dist < 0 or dist > length:
        return -1, length
    return geom, dist


def walls_between(m, d, origin, target, exclude_body, target_geom, max_hits=10):
    """Number of geoms (other than the target) crossed on the straight line origin->target."""
    origin = np.asarray(origin, float)
    target = np.asarray(target, float)
    count, exclude = 0, exclude_body
    for _ in range(max_hits):
        geom, dist = first_hit(m, d, origin, target, exclude)
        if geom < 0 or geom == target_geom:
            break
        count += 1
        direction = (target - origin) / np.linalg.norm(target - origin)
        origin = origin + direction * dist
        exclude = int(m.geom_bodyid[geom])
    return count


def relative_bearing(origin, yaw, target):
    """Bearing of target from origin relative to heading yaw, degrees in (-180, 180]."""
    dx, dy = target[0] - origin[0], target[1] - origin[1]
    b = np.degrees(np.arctan2(dy, dx) - yaw)
    b = (b + 180.0) % 360.0 - 180.0
    return 180.0 if b == -180.0 else float(b)


def thermal(origin, yaw, casualty_pos, visible):
    """16x12 grid: 0.1 background, a Gaussian blob peaking at 0.9 where a visible casualty is.

    The grid is a forward-looking image (60 x 45 degree field of view), row 0 at the top,
    column 0 on the left. `visible` means within THERMAL_RANGE and in line of sight.
    """
    grid = np.full((THERMAL_H, THERMAL_W), 0.1)
    if not visible:
        return grid
    rel = np.asarray(casualty_pos, float) - np.asarray(origin, float)
    dist = float(np.linalg.norm(rel[:2]))
    az = np.radians(relative_bearing(origin, yaw, casualty_pos))       # + is left
    el = np.arctan2(rel[2], max(dist, 1e-6))                              # + is up
    u = (0.5 - az / THERMAL_FOV_H) * THERMAL_W - 0.5                      # column centre
    v = (0.5 - el / THERMAL_FOV_V) * THERMAL_H - 0.5                      # row centre
    cell = THERMAL_FOV_H / THERMAL_W
    sigma = max(0.8, np.arctan2(0.3, max(dist, 1e-6)) / cell)             # a body is ~0.6 m long
    cols, rows = np.meshgrid(np.arange(THERMAL_W), np.arange(THERMAL_H))
    grid += 0.8 * np.exp(-((cols - u) ** 2 + (rows - v) ** 2) / (2 * sigma**2))
    return grid


def acoustic(origin, yaw, casualty_pos, walls, rng, noise=0.05):
    """{"bearing": deg relative to heading, "level": 0..1}, falling with distance and walls."""
    dist = float(np.linalg.norm(np.asarray(casualty_pos, float)[:2] - np.asarray(origin, float)[:2]))
    level = max(0.0, 1.0 - dist / 8.0) * (0.5**walls) + rng.normal(0.0, noise)
    bearing = relative_bearing(origin, yaw, casualty_pos) + rng.normal(0.0, 5.0)
    bearing = (bearing + 180.0) % 360.0 - 180.0
    return {"bearing": round(float(bearing), 1), "level": round(float(np.clip(level, 0.0, 1.0)), 3)}


def make_renderer(m, height=240, width=320):
    """An offscreen renderer, or None where no GL context is available (CI, headless without EGL)."""
    try:
        return mujoco.Renderer(m, height=height, width=width)
    except Exception:  # noqa: BLE001  (no GL context: run without camera frames)
        return None


def camera_jpeg(d, renderer, name="scout_cam", quality=70):
    """The Scout camera frame as a base64 JPEG string, or None without a renderer or Pillow."""
    if renderer is None:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    renderer.update_scene(d, camera=name)
    buf = io.BytesIO()
    Image.fromarray(renderer.render()).save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")
