"""Scout RGB-D (Y9): the depth camera's measured 3D points for sensors/scout.points and .points_from.

The Scout's depth camera is the Orbbec DaBai built into the LIMO Pro (docs/hardware.md). The sim renders
it from `scout_cam` with MuJoCo's depth buffer (metric depth along the optical axis), deprojects every
sampled pixel through the camera intrinsics into the scene frame, and keeps at most MAX_POINTS points per
frame, sampled on an even pixel grid so the cloud covers the whole view. Robot geoms (group 3: the
Scout and the Responder) are hidden from the depth render, as a real camera would not see its own body
and perception should not map the Responder.

Measured, not truth: each depth gets stereo-style noise that grows with distance squared (seeded, so
runs repeat), and pixels outside the depth range (MIN_RANGE..MAX_RANGE) are dropped, as a real
depth camera returns no value there. The DaBai's range and FOV are not in docs/hardware.md yet
("not checked"), so MIN_RANGE, MAX_RANGE and NOISE_PER_M2 are stated assumptions for a small stereo
camera, and the FOV is scout_cam's 60 degrees vertical.

`frame()` returns {"points": [[x, y, z], ...], "points_from": [x, y, z]} for one render; `colour()` gives
the matching RGB frame (the existing scout camera JPEG stays in sim/sensors.py).
"""

import math

import mujoco
import numpy as np

CAMERA = "scout_cam"
WIDTH, HEIGHT = 128, 96        # depth render size; points are sampled from it
MAX_POINTS = 2048              # coord/messages.py SensorsScout.points max_length
MIN_RANGE, MAX_RANGE = 0.15, 4.0   # metres: assumed DaBai working range (not yet in docs/hardware.md)
NOISE_PER_M2 = 0.004           # depth noise sigma = NOISE_PER_M2 * depth^2 (stereo error grows with z^2)
ROBOT_GROUP = 3                # Scout and Responder geoms (sim/scenes/*.xml), hidden from the depth render


class RGBD:
    def __init__(self, m, width=WIDTH, height=HEIGHT, seed=0, noise=NOISE_PER_M2, camera=CAMERA):
        """`camera`: the Scout's depth camera in this scene (scout_cam, or the true-scale robot's depth_cam)."""
        self.m = m
        self.cam = m.camera(camera).id
        self.width, self.height = width, height
        self.rng = np.random.default_rng(seed)
        self.noise = noise
        self.renderer = _depth_renderer(m, height, width)
        self.option = mujoco.MjvOption()
        self.option.geomgroup[ROBOT_GROUP] = 0
        fovy = math.radians(float(m.cam_fovy[self.cam]))
        self.f = (height / 2) / math.tan(fovy / 2)           # focal length in pixels (square pixels)
        self.cx, self.cy = (width - 1) / 2, (height - 1) / 2
        self.pixels = _grid(width, height, MAX_POINTS)        # (rows, cols) sampled every frame

    @property
    def available(self):
        return self.renderer is not None

    def depth(self, d):
        """The metric depth image (H x W, metres along the optical axis), robot geoms hidden."""
        self.renderer.update_scene(d, camera=self.cam, scene_option=self.option)
        return self.renderer.render()

    def frame(self, d):
        """{"points": up to MAX_POINTS measured scene-frame points, "points_from": camera position}."""
        if not self.available:
            return None
        depth = self.depth(d)
        rows, cols = self.pixels
        z = depth[rows, cols].astype(float)
        keep = (z >= MIN_RANGE) & (z <= MAX_RANGE)
        rows, cols, z = rows[keep], cols[keep], z[keep]
        if self.noise:
            z = z + self.rng.normal(0.0, 1.0, z.shape) * self.noise * z * z
        # Camera frame (MuJoCo): x right, y up, looking down -z.
        x = (cols - self.cx) / self.f * z
        y = -(rows - self.cy) / self.f * z
        cam_pts = np.stack([x, y, -z], axis=1)
        rot = self.m_rot(d)
        origin = d.cam_xpos[self.cam]
        world = cam_pts @ rot.T + origin
        return {"points": np.round(world, 3).tolist(), "points_from": [round(float(v), 3) for v in origin]}

    def m_rot(self, d):
        return d.cam_xmat[self.cam].reshape(3, 3)


def _grid(width, height, cap):
    """Evenly spaced (rows, cols) with at most `cap` pixels, covering the whole image."""
    step = max(1, math.ceil(math.sqrt(width * height / cap)))
    rows, cols = np.meshgrid(np.arange(step // 2, height, step), np.arange(step // 2, width, step), indexing="ij")
    rows, cols = rows.ravel(), cols.ravel()
    return rows[:cap], cols[:cap]


def _depth_renderer(m, height, width):
    """A depth-mode renderer, or None without a GL context (same rule as sim/sensors.make_renderer)."""
    from sim import sensors

    r = sensors.make_renderer(m, height=height, width=width)
    if r is not None:
        r.enable_depth_rendering()
    return r
