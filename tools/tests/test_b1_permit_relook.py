"""A B1 slab seen by the Scout revokes a move permit until a fresh clear scan."""

import pytest

pytest.importorskip("mujoco")

import mujoco

from planner.permit import Permits, RES
from sim.levels import LevelWorld
from tools.run_b2 import drop_slab, scene_with_slab


def test_b1_slab_shift_needs_a_fresh_scout_observation(tmp_path):
    world = LevelWorld(path=scene_with_slab(tmp_path), render=False)
    world._set_pose((0.4, 1.45), 0.0)
    world._set_z(-0.6)
    mujoco.mj_forward(world.m, world.d)
    assert world.level() == "B1"

    route = [[i, 29, -12] for i in range(10, 25)]
    permits = Permits()
    permits.on_route_proposed({"id": "b1-water", "cells": route})
    granted = permits.on_route_verified({"id": "b1-water", "ok": True}, 1.0)
    assert granted[0][0] == "permit/route" and granted[0][1]["granted"]

    # This is the actual B1 scene and MuJoCo LiDAR, with a new slab on the route.
    drop_slab(world, (1.0, 1.45), -0.6)
    blocked_scan = world.sensors_message(camera=False)
    revoked = permits.on_sensors(blocked_scan, 2.0)
    assert revoked[0][0] == "permit/route"
    assert revoked[0][1]["granted"] is False
    assert revoked[0][1]["evidence"][-1]["kind"] == "shift"
    assert any(topic == "scout/goto" for topic, _ in revoked)

    # Time, a quiet hazard update, and another blocked look cannot restore permission.
    assert permits.on_hazards([], 10.0) == []
    permits.on_sensors(blocked_scan, 20.0)
    assert not permits.granted("b1-water")

    # Clear the slab in the scene. The planner has no truth feed: it still holds the route.
    body = world.m.body("x1").id
    adr = world.m.jnt_qposadr[world.m.body_jntadr[body]]
    world.d.qpos[adr:adr + 3] = [-3.0, -3.0, -3.0]
    mujoco.mj_forward(world.m, world.d)
    assert not permits.granted("b1-water")

    fresh = world.sensors_message(camera=False)
    assert fresh["lidar"][0] > blocked_scan["lidar"][0]
    restored = permits.on_sensors(fresh, 21.0)
    assert restored[0][0] == "permit/route"
    assert restored[0][1]["granted"] is True
    assert restored[0][1]["evidence"][-1]["kind"] == "fresh_scan"
    assert permits.granted("b1-water")
