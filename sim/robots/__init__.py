"""True-scale robot models (Y7a), built from docs/hardware.md (Y7b).

    from sim import robots
    m, d = robots.load("responder")                    # the robot alone on a floor, arm stowed
    spec = mujoco.MjSpec.from_file("my_scene.xml")
    robots.attach(spec, "scout", pos=(1, 2, 0), yaw=90, prefix="scout1/")
    robots.attach(spec, "responder", pos=(0, 0, 0))    # prefix defaults to "<name>/"

Each model's root is a mocap body named like the robot (`scout`, `responder`, after the prefix), with
its origin on the ground under the centre of the base, x forward. Sensor sites carry the spec table
names: lidar, depth_cam or rgbd_cam, thermal, mic_array, imu or base_imu/arm_imu, plus tool, arm_mount
and supply_deck on the Responder. The figures below are the spec's, and sim/tests/test_robots.py
checks the models against them.
"""

import math
from pathlib import Path

import mujoco
import numpy as np

HERE = Path(__file__).parent

# docs/hardware.md, Summary and "Sensor positions" tables (metres, kilograms).
SPEC = {
    "scout": {
        "part": "AgileX LIMO Pro",
        "size": (0.322, 0.220, 0.251),       # L x W x H, maker
        "ground_clearance": 0.024,
        "mass": 5.2,                          # with add-ons, estimate
        "sensors": {
            "lidar": (0.00, 0.00, 0.26),
            "depth_cam": (0.15, 0.00, 0.18),
            "thermal": (0.15, 0.00, 0.21),
            "mic_array": (-0.05, 0.00, 0.27),
            "imu": (0.00, 0.00, 0.10),
        },
    },
    "responder": {
        "part": "Clearpath Jackal",
        "size": (0.508, 0.430, 0.250),       # base, maker
        "height_with_mast": 0.70,             # about, estimate
        "ground_clearance": 0.065,
        "mass": 25.7,                         # with arm, sensors, compute and supplies, estimate
        "supply_kit_mass": 1.5,               # part of the 25.7 kg; the kit itself is Y2's
        "sensors": {
            "lidar": (-0.15, 0.00, 0.70),
            "rgbd_cam": (0.24, 0.00, 0.30),
            "thermal": (0.24, 0.05, 0.30),
            "mic_array": (-0.20, 0.00, 0.27),
            "arm_mount": (0.10, 0.00, 0.25),
            "supply_deck": (-0.10, 0.00, 0.26),
        },
        "arm": {"part": "Kinova Gen3 lite", "dof": 6, "mass": 5.4, "reach": 0.76, "payload": 0.5},
    },
}

# Geom types as plain ints: a numpy int is not `in` a tuple of mjtGeom members.
PLANE, CAPSULE, CYLINDER, BOX = (int(t) for t in (mujoco.mjtGeom.mjGEOM_PLANE, mujoco.mjtGeom.mjGEOM_CAPSULE,
                                                 mujoco.mjtGeom.mjGEOM_CYLINDER, mujoco.mjtGeom.mjGEOM_BOX))
ARM_JOINTS = ("j1", "j2", "j3", "j4", "j5", "j6")
# Folded diagonally over the right half of the top plate (radians, j1..j6): every arm part stays inside
# the base footprint, below 0.6 m (under the mast's LiDAR), more than 0.1 m from the mast and behind
# the front cameras. Found by a grid search over j1, j2, j3, j5 within the joint limits.
STOWED = (-2.5, 1.8, -2.5, 0.0, -1.6, 0.0)


def path(name: str) -> Path:
    if name not in SPEC:
        raise ValueError(f"unknown robot {name!r}; one of {sorted(SPEC)}")
    return HERE / f"{name}.xml"


def attach(scene: mujoco.MjSpec, name: str, pos=(0.0, 0.0, 0.0), yaw: float = 0.0,
           prefix: str | None = None) -> mujoco.MjsBody:
    """Add robot `name` to `scene` at `pos` (its ground point) facing `yaw` degrees; return its root body.

    Every name in the robot gets `prefix` (default "<name>/"), so two Scouts need two prefixes.
    """
    child = mujoco.MjSpec.from_file(str(path(name)))
    half = math.radians(yaw) / 2
    frame = scene.worldbody.add_frame(pos=list(pos), quat=[math.cos(half), 0, 0, math.sin(half)])
    prefix = f"{name}/" if prefix is None else prefix
    scene.attach(child, prefix=prefix, frame=frame)
    return scene.body(prefix + name)


def stow(m: mujoco.MjModel, d: mujoco.MjData, prefix: str = "responder/") -> None:
    """Put the Responder's arm in the stowed pose and hold it there (qpos and servo targets)."""
    for joint, angle in zip(ARM_JOINTS, STOWED, strict=True):
        d.qpos[m.joint(prefix + joint).qposadr[0]] = angle
        d.ctrl[m.actuator(prefix + joint).id] = angle
    mujoco.mj_forward(m, d)


def can_lift(mass_kg: float) -> bool:
    """True if the Gen3 lite's rated payload covers `mass_kg` (heavier debris is pushed, not lifted)."""
    return mass_kg <= SPEC["responder"]["arm"]["payload"]


def load(name: str):
    """The robot alone on a floor: (model, data), Responder arm stowed."""
    scene = mujoco.MjSpec()
    scene.worldbody.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[5, 5, 0.1])
    attach(scene, name)
    m = scene.compile()
    d = mujoco.MjData(m)
    if name == "responder":
        stow(m, d)
    mujoco.mj_forward(m, d)
    return m, d


def extent(m: mujoco.MjModel, d: mujoco.MjData, body: str):
    """World axis-aligned (low, high) corners over the geoms of `body` and everything below it."""
    root = m.body(body).id
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for g in range(m.ngeom):
        b = m.geom_bodyid[g]
        while b not in (root, 0):
            b = m.body_parentid[b]
        if b != root or int(m.geom_type[g]) == PLANE:
            continue
        for corner in _corners(m, d, g):
            lo, hi = np.minimum(lo, corner), np.maximum(hi, corner)
    return lo, hi


def _corners(m, d, g):
    """Points bounding geom g (box corners; cylinder and capsule end-cap rims) in world coordinates."""
    t, size, R, c = int(m.geom_type[g]), m.geom_size[g], d.geom_xmat[g].reshape(3, 3), d.geom_xpos[g]
    if t == BOX:
        local = [np.array([sx, sy, sz]) * size for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    elif t in (CYLINDER, CAPSULE):
        r, h = size[0], size[1] + (size[0] if t == CAPSULE else 0)
        local = [np.array([r * math.cos(a), r * math.sin(a), z]) for a in np.linspace(0, 2 * math.pi, 16,
                                                                                    endpoint=False)
                 for z in (-h, h)]
    else:
        local = [np.zeros(3)]
    return [c + R @ p for p in local]
