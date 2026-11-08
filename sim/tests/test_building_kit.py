"""Checks for BUILDING-KIT (ref BUILDING-KIT): building scene carries kit on Responder deck."""

import pytest

from sim import responder as R
from sim import scene
from sim.sensors import ROBOT_GROUP


@pytest.fixture(scope="module")
def building_model():
    m, d = scene.load(scene.BUILDING)
    return m, d


def test_building_scene_has_kit_bodies_and_welds(building_model):
    m, d = building_model
    for item in ("water", "first_aid_kit", "radio"):
        assert m.body(item).id >= 0, f"body {item} missing from building scene"
        eq_name = f"carry_{item}"
        eq_id = m.equality(eq_name).id
        assert eq_id >= 0, f"equality {eq_name} missing from building scene"
        assert d.eq_active[eq_id] == 1, f"equality {eq_name} should start active"


def test_responder_frame_z_is_above_floor(building_model):
    m, d = building_model
    rpos = d.xpos[m.body("responder").id]
    assert abs(rpos[2] - 0.05) < 1e-4, f"expected responder z ~ 0.05, got {rpos[2]}"
    # Floor ray starts at z - RIDE_Z; with z=0.05 and RIDE_Z=0.05, it sits at ground z=0.0
    assert rpos[2] >= R.RIDE_Z


def test_building_carried_supplies_are_robot_geoms(building_model):
    m, _ = building_model
    for item in ("water", "first_aid_kit", "radio"):
        body_id = m.body(item).id
        for g in range(m.ngeom):
            if m.geom_bodyid[g] == body_id:
                assert int(m.geom_group[g]) == ROBOT_GROUP, f"{item} geom not in group {ROBOT_GROUP}"


def test_responder_holds_kit_in_building_scene(building_model):
    m, d = building_model
    resp = R.Responder(m, d)
    for item in ("water", "first_aid_kit", "radio"):
        assert resp.holding(item), f"responder should be holding {item}"
        assert item in resp.status()["carrying"]


def test_building_place_supply_not_refused_as_unloaded(building_model):
    m, d = building_model
    resp = R.Responder(m, d)
    out = resp.on_action({"action": "place_supply", "route": "r0", "item": "water"})
    assert "water is not loaded" not in out.get("reason", "")
    assert out["outcome"] == "done"
    assert not resp.holding("water")
