"""Y7a: the true-scale robot models match docs/hardware.md (Y7b) and work in a scene."""

import math
import re
from pathlib import Path

import mujoco
import numpy as np
import pytest

from sim import robots as R

DOC = (Path(__file__).parents[2] / "docs" / "hardware.md").read_text()
ARM = ("shoulder", "upper_arm", "forearm", "wrist1", "wrist2", "hand", "pad_l", "pad_r")


def total_mass(m, root):
    """Mass of `root` and every body below it."""
    rid = m.body(root).id
    out = 0.0
    for b in range(m.nbody):
        a = b
        while a not in (rid, 0):
            a = m.body_parentid[a]
        out += m.body_mass[b] if a == rid else 0.0
    return out


def arm_points(m, d):
    return np.array([p for g in ARM for p in R._corners(m, d, m.geom(f"responder/{g}").id)])


def set_arm(m, d, q):
    for joint, angle in zip(R.ARM_JOINTS, q, strict=True):
        d.qpos[m.joint(f"responder/{joint}").qposadr[0]] = angle
    mujoco.mj_kinematics(m, d)


@pytest.fixture(scope="module", params=["scout", "responder"])
def robot(request):
    name = request.param
    m, d = R.load(name)
    return name, m, d


def test_spec_figures_are_the_docs_figures():
    """SPEC must quote docs/hardware.md, so a change there shows up here."""
    for name, row in (("scout", "322 x 220 x 251 mm"), ("responder", "508 x 430 x 250 mm")):
        assert row in DOC
        assert tuple(round(v * 1000) for v in R.SPEC[name]["size"]) == tuple(int(n) for n in re.findall(r"\d+", row))
    assert "24 mm ground clearance" in DOC and "65 mm ground clearance" in DOC
    assert "about 5.2 kg with add-ons" in DOC and "about 25.7 kg" in DOC and "supply kit about 1.5 kg" in DOC
    assert "6 DoF, 5.4 kg, 0.5 kg payload, 760 mm reach" in DOC
    table = DOC.split("## Sensor positions")[1].split("##")[0]
    for name, rows in (("scout", ("lidar", "depth_cam", "thermal", "mic_array", "imu")),
                       ("responder", ("lidar", "rgbd_cam", "thermal", "mic_array", "arm_mount", "supply_deck"))):
        for key in rows:
            x, y, z = R.SPEC[name]["sensors"][key]
            assert f"| {x:.2f}, {y:.2f}, {z:.2f} |" in table, (name, key)


def test_footprint_and_clearance_are_true_scale(robot):
    name, m, d = robot
    lo, hi = R.extent(m, d, f"{name}/{name}")
    length, width, _ = R.SPEC[name]["size"]
    assert hi[0] - lo[0] == pytest.approx(length, abs=0.005)
    assert hi[1] - lo[1] == pytest.approx(width, abs=0.005)
    assert lo[2] == pytest.approx(0.0, abs=1e-6)  # wheels on the ground
    chassis = "chassis_lower" if name == "scout" else "chassis"
    g = m.geom(f"{name}/{chassis}").id
    assert d.geom_xpos[g][2] - m.geom_size[g][2] == pytest.approx(R.SPEC[name]["ground_clearance"], abs=1e-6)


def test_heights():
    m, d = R.load("scout")
    _, hi = R.extent(m, d, "scout/scout")
    # The spec table puts the LiDAR centre at 0.26 m and the mic array at 0.27 m, a little above the
    # maker's 251 mm (which is without the added mic array): the top lands at about 0.28 m.
    assert 0.251 <= hi[2] <= 0.28
    m, d = R.load("responder")
    g = m.geom("responder/top_plate").id
    assert d.geom_xpos[g][2] + m.geom_size[g][2] == pytest.approx(0.25, abs=1e-6)
    _, hi = R.extent(m, d, "responder/responder")
    assert hi[2] == pytest.approx(R.SPEC["responder"]["height_with_mast"], abs=0.04)


def test_masses_add_up_to_the_spec():
    m, _ = R.load("scout")
    assert total_mass(m, "scout/scout") == pytest.approx(R.SPEC["scout"]["mass"], abs=0.1)
    m, _ = R.load("responder")
    resp = R.SPEC["responder"]
    # 25.7 kg includes Y2's 1.5 kg supply kit, which is not part of this model.
    assert total_mass(m, "responder/responder") == pytest.approx(resp["mass"] - resp["supply_kit_mass"], abs=0.15)
    assert total_mass(m, "responder/arm_base") == pytest.approx(resp["arm"]["mass"], abs=1e-6)


def test_sensor_sites_sit_where_the_spec_puts_them(robot):
    name, _m, d = robot
    for key, pos in R.SPEC[name]["sensors"].items():
        assert d.site(f"{name}/{key}").xpos == pytest.approx(pos, abs=1e-6), key


def test_cameras_and_imus():
    m, d = R.load("scout")
    assert m.sensor("scout/imu_accel").dim[0] == 3 and m.sensor("scout/imu_gyro").dim[0] == 3
    for cam, fovy in (("depth_cam", 60), ("thermal_cam", 44.3)):
        c = m.camera(f"scout/{cam}")
        assert c.fovy[0] == pytest.approx(fovy)
        assert d.cam_xmat[c.id].reshape(3, 3)[:, 2] == pytest.approx([-1, 0, 0], abs=1e-6)  # looks along +x
    # Lepton 3.5: 160 x 120 over 57 degrees horizontal.
    assert 2 * math.degrees(math.atan(math.tan(math.radians(28.5)) * 120 / 160)) == pytest.approx(44.3, abs=0.05)
    m, d = R.load("responder")
    look = -d.cam_xmat[m.camera("responder/rgbd_cam").id].reshape(3, 3)[:, 2]
    assert math.degrees(math.atan2(-look[2], look[0])) == pytest.approx(15, abs=1e-4)  # tilted 15 degrees down
    for name in ("responder/base_imu_accel", "responder/arm_imu_accel"):
        assert m.sensor(name).dim[0] == 3


def test_arm_reach_is_760_mm():
    m, d = R.load("responder")
    set_arm(m, d, (0, math.pi / 2, 0, 0, 0, 0))  # straight out forward, level with the shoulder
    shoulder = d.xpos[m.body("responder/upper_arm").id]
    tool = d.site("responder/tool").xpos
    assert tool[0] - shoulder[0] == pytest.approx(R.SPEC["responder"]["arm"]["reach"], abs=1e-6)
    assert tool[2] == pytest.approx(shoulder[2], abs=1e-6)
    assert m.nu == 8 and all(m.joint(f"responder/{j}").range[1] > 2.6 for j in R.ARM_JOINTS)


def test_stowed_arm_stays_on_the_robot_and_under_the_lidar():
    m, d = R.load("responder")
    for _ in range(1000):  # 2 s: the servos hold the pose
        mujoco.mj_step(m, d)
    q = [d.qpos[m.joint(f"responder/{j}").qposadr[0]] for j in R.ARM_JOINTS]
    assert q == pytest.approx(R.STOWED, abs=1e-3)
    pts = arm_points(m, d)
    length, width, _ = R.SPEC["responder"]["size"]
    assert (abs(pts[:, 0]) <= length / 2).all() and (abs(pts[:, 1]) <= width / 2).all()
    assert pts[:, 2].min() > 0.25 and pts[:, 2].max() < 0.6  # above the top plate, below the LiDAR
    assert np.hypot(pts[:, 0] + 0.15, pts[:, 1]).min() > 0.1  # clear of the mast
    assert d.site("responder/tool").xpos[0] < 0.226  # behind the front cameras


def test_gripper_payload():
    assert R.can_lift(0.5) and R.can_lift(0.4)       # water bottle, first-aid kit
    assert not R.can_lift(0.6) and not R.can_lift(2)  # the backup scene's 2 kg rubble is pushed


def test_two_scouts_and_a_responder_attach_to_one_scene():
    scene = mujoco.MjSpec()
    scene.worldbody.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[5, 5, 0.1])
    R.attach(scene, "scout", pos=(1, 0, 0), prefix="scout1/")
    R.attach(scene, "scout", pos=(1, 1, 0), yaw=90, prefix="scout2/")
    R.attach(scene, "responder", pos=(-1, 0, 0), yaw=180)
    m = scene.compile()
    d = mujoco.MjData(m)
    R.stow(m, d)
    for _ in range(200):
        mujoco.mj_step(m, d)
    assert np.isfinite(d.qpos).all()
    assert d.site("scout2/lidar").xpos == pytest.approx([1, 1, 0.26], abs=1e-6)
    assert d.site("scout2/depth_cam").xpos == pytest.approx([1, 1.15, 0.18], abs=1e-6)  # yaw 90: front is +y
    assert d.site("responder/lidar").xpos == pytest.approx([-0.85, 0, 0.70], abs=1e-6)
    assert m.body("scout1/scout").mocapid[0] >= 0 and m.body("responder/responder").mocapid[0] >= 0
    # Moving a mocap root carries its sensors.
    d.mocap_pos[m.body("scout1/scout").mocapid[0]] = [2, 0, 0]
    mujoco.mj_forward(m, d)
    assert d.site("scout1/lidar").xpos == pytest.approx([2, 0, 0.26], abs=1e-6)


def test_robot_geoms_are_group_3_and_only_finger_pads_collide(robot):
    name, m, _d = robot
    root = m.body(f"{name}/{name}").id
    for g in range(m.ngeom):
        if int(m.geom_type[g]) == R.PLANE:
            continue
        assert m.geom_group[g] == 3
        collides = m.geom_contype[g] or m.geom_conaffinity[g]
        assert bool(collides) == m.geom(g).name.split("/")[-1].startswith("pad_"), m.geom(g).name
    assert root > 0


def test_unknown_robot():
    with pytest.raises(ValueError):
        R.path("drone")
