"""Y2 checks: the Responder carries the full supply kit and can carry found material (a board used as a
splint) to a casualty, within the real arm's 0.5 kg payload."""

import math

import numpy as np
import pytest

from sim import responder as R
from sim.world import World

KIT = ("bandage", "splint", "thermal_blanket")


@pytest.fixture
def world():
    w = World(render=False)
    w._set_pose((-1.2, -1.7), 0.0)      # Scout parked out of the way
    return w


@pytest.fixture
def resp(world):
    return R.Responder(world.m, world.d, clock=lambda: world.t)


def pos_of(world, name):
    return world.d.xpos[world.m.body(name).id].copy()


def settle(world, seconds=1.0):
    for _ in range(int(seconds / 0.1)):
        world.tick(0.1)


def test_kit_starts_on_the_deck_below_the_block_slot(world, resp):
    for item in KIT:
        assert resp.holding(item), item
        assert item in resp.status()["carrying"]
        top = pos_of(world, item)[2] - resp.pos[2]
        assert top < R.BLOCK_SLOT_Z, f"{item} sits above the gripped-block slot"
    assert world.m.body_mass[world.m.body("b16").id] <= R.ARM_PAYLOAD_KG


def test_each_kit_item_is_placed_on_the_floor_in_front(world, resp):
    settle(world)
    for item in ("splint", "bandage", "thermal_blanket"):       # top of each stack first
        out = resp.on_action({"action": "place_supply", "route": "r0", "item": item})
        assert out["outcome"] == "done", out
        assert not resp.holding(item)
    settle(world, 2.0)
    fwd = np.array([math.cos(resp.yaw), math.sin(resp.yaw)])
    for item in KIT:
        p = pos_of(world, item)
        assert p[2] < 0.06, f"{item} should rest on the floor, z={p[2]:.3f}"
        assert float(np.dot(p[:2] - resp.pos[:2], fwd)) > R.HALF_LEN, f"{item} should be in front"
    for item in ("water", "first_aid_kit", "radio"):
        assert resp.holding(item), f"{item} stays on the deck"


def test_found_board_is_carried_to_the_casualty_as_a_splint(world, resp):
    resp._set_pose((2.1, 0.1), 0.0)                 # beside the board, facing the east wall
    settle(world, 0.5)
    grip = resp.on_action({"action": "grip", "route": "r0", "item": "splint", "block": "b16"})
    assert grip["outcome"] == "done", grip
    assert resp.holding("b16")
    released_early = resp.on_action({"action": "release", "route": "r0", "item": "splint", "block": "b17"})
    assert released_early["outcome"] == "refused"   # a block that does not exist
    resp._set_pose((1.95, 0.5), math.pi / 2)        # in front of casualty c1 (2.0, 1.0), facing it
    settle(world, 0.5)
    assert np.linalg.norm(pos_of(world, "b16")[:2] - resp.pos[:2]) < 0.05, "the board rides on the deck"
    out = resp.on_action({"action": "place_supply", "route": "r0", "item": "splint", "block": "b16"})
    assert out["outcome"] == "done" and "as a splint" in out["reason"], out
    after = resp.on_action({"action": "release", "route": "r0", "item": "splint", "block": "b16"})
    assert after["outcome"] == "done" and "not holding" in after["reason"]
    settle(world, 2.0)
    board = pos_of(world, "b16")
    assert board[2] < 0.04
    assert board[1] > resp.pos[1] + R.HALF_LEN, "set down toward the casualty"
    assert np.linalg.norm(board[:2] - np.array([2.0, 1.0])) < 0.5


def test_found_material_must_fit_the_arm_payload(world, resp):
    resp._set_pose((1.25, 0.2), math.pi / 2)        # beside rubble b11 (1.5 kg)
    settle(world, 0.5)
    out = resp.on_action({"action": "grip", "route": "r0", "item": "splint", "block": "b11"})
    assert out["outcome"] == "refused" and "0.5 kg" in out["reason"], out
    assert not resp.holding("b11")
    clear = resp.on_action({"action": "grip", "route": "r0", "block": "b11"})   # clearing: slid aside
    assert clear["outcome"] == "done", clear
    aside = resp.on_action({"action": "release", "route": "r0", "block": "b11"})
    assert aside["outcome"] == "done" and not resp.holding("b11")


def test_kit_item_missing_from_a_scene_is_refused(world, resp):
    eq = world.m.equality("carry_splint").id
    resp._eq = lambda name, real=resp._eq: -1 if name == "carry_splint" else real(name)
    out = resp.on_action({"action": "place_supply", "route": "r0", "item": "splint"})
    assert out["outcome"] == "refused" and "not loaded" in out["reason"]
    assert world.d.eq_active[eq], "the real weld was not touched"
