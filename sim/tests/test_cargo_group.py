"""What a robot carries is in the robot geom group (3) in every scene, so the Scout's sensors skip it.

sim/sensors.py and sim/rgbd.py hide group 3, "the robots and what they carry". A supply left out of
it is seen floating over floor the LiDAR passes through the chassis to: perception/cloud.py reads it
as an overhang and revokes the routes beside the Responder (#52 seed 4).
"""

from pathlib import Path

import mujoco
import pytest

from sim.sensors import ROBOT_GROUP

SCENES = sorted((Path(__file__).resolve().parents[1] / "scenes").glob("*.xml"))


def carried(m):
    """{geom name: group} for every geom on a body a carry_* weld holds."""
    out = {}
    for e in range(m.neq):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_EQUALITY, e) or ""
        if not name.startswith("carry_"):
            continue
        body = m.eq_obj2id[e]
        for g in range(m.ngeom):
            if m.geom_bodyid[g] == body:
                out[mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g)] = int(m.geom_group[g])
    return out


@pytest.mark.parametrize("path", SCENES, ids=lambda p: p.name)
def test_carried_supplies_are_robot_geoms(path):
    m = mujoco.MjModel.from_xml_path(str(path))
    wrong = {g: grp for g, grp in carried(m).items() if grp != ROBOT_GROUP}
    assert not wrong, f"{path.name}: carried geoms outside group {ROBOT_GROUP}: {wrong}"


def test_backup_scene_carries_its_kit():
    m = mujoco.MjModel.from_xml_path(str(Path(__file__).resolve().parents[1] / "scenes" / "backup.xml"))
    assert {"water_supply", "first_aid_kit_supply", "radio_supply"} <= set(carried(m))
