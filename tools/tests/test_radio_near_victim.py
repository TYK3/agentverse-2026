"""RADIO-NEAR-VICTIM: the radio is set down beside casualty c1 through the real planner and sim (ref RADIO-NEAR-VICTIM).

The same real-lane run as tools/tests/test_deliver.py (its helpers imported, unchanged): the sim
(sim.start, loop=False: MuJoCo world, physics check, Responder) and the planner loop (router, physics
verify, gate, dispatch) on one in-process bus, GEMINI_MODE off, the world ticked by hand in sim time.
The mission asks for item "radio"; the operator approves; the planner dispatches move, place_supply and
release of the radio; the sim's Responder carries them out with real MuJoCo bodies.

Checked: nothing moves before approval; the dispatched actions name the radio; the Responder arrives,
places it and no longer carries it, and keeps the rest of its load; the radio ends on the floor within
NEAR_CASUALTY of c1, at rest, and upright (its own z axis within UPRIGHT_DEG of vertical), so a casualty
who cannot sit up can still reach and use it. At ground level on the backup scene: B1 has no
Responder or kit yet (#267).
"""

import asyncio
import math

import pytest

pytest.importorskip("mujoco")

import mujoco
import numpy as np

import sim
from planner import loop as L
from planner.route import RoutePlanner
from planner.tests.test_loop import Bus, Clock, OffGem
from tools.tests.test_deliver import C1, GOAL, START, cell, map_from_blocks

ITEM = "radio"
NEAR_CASUALTY = 0.6                # metres, as test_deliver's water check
UPRIGHT_DEG = 30.0


@pytest.fixture(scope="module")
def run():
    async def go():
        bus, clock = Bus(), Clock()
        world = await sim.start(bus, loop=False)
        world._set_pose((-1.2, -1.7), 0.0)          # Scout parked out of the Responder's way
        router = RoutePlanner(bus)
        bus.subscribe("map/cells", router.update_map)
        lp = L.Loop(bus, router, gem=OffGem(), clock=clock, review_timeout=5.0).attach()
        await bus.publish("map/cells", map_from_blocks(bus.of("scene/loaded")[0]["blocks"]))
        await bus.publish("map/hazards", [])
        await bus.publish("map/casualties", [C1])
        await lp.mission(cell(*START), cell(*GOAL), goal_text=f"deliver {ITEM} to c1", item=ITEM)
        (route,) = bus.of("route/proposed")
        (req,) = bus.of("gate/request")
        moved_before = list(bus.of("responder/action"))
        await bus.publish("gate/answer", {"id": req["id"], "approved": True, "by": "operator"})
        r = world.responder
        for _ in range(600):                         # at most 60 s of sim time
            r.step(0.1)
            world.tick(0.1)
            await asyncio.sleep(0)
            if r.state != "moving" and not r.queue:
                break
        for _ in range(10):                          # one second for the radio to settle
            world.tick(0.1)
        return world, r, route["id"], bus, moved_before

    return asyncio.run(go())


def test_nothing_moves_before_approval_then_the_radio_is_dispatched(run):
    _world, _r, rid, bus, moved_before = run
    assert moved_before == []
    assert [(a["action"], a["route"], a["item"]) for a in bus.of("responder/action")] == [
        ("move", rid, ITEM), ("place_supply", rid, ITEM), ("release", rid, ITEM)]


def test_the_responder_places_the_radio_and_keeps_the_rest(run):
    _world, r, rid, _bus, _ = run
    outcomes = [e["outcome"] for e in r.log]
    assert "refused" not in outcomes and "blocked" not in outcomes, r.log
    assert r.state == "arrived"
    done = [(e["perception"].split("], ")[-1], e["reason"]) for e in r.log if e["outcome"] == "done"]
    assert [p for p, _ in done] == [f"move {rid}", f"place_supply {ITEM}", f"release {ITEM}"], r.log
    assert done[1][1].startswith(f"placed {ITEM} at ")
    carrying = r.status()["carrying"]
    assert ITEM not in carrying and {"water", "first_aid_kit"} <= set(carrying)


def test_the_radio_is_beside_c1_on_the_floor_upright_and_at_rest(run):
    world, _r, _rid, _bus, _ = run
    body = world.m.body(ITEM).id
    pos = world.d.xpos[body]
    c1 = world.d.xpos[world.m.body("casualty_c1").id]
    gap = float(np.linalg.norm(pos[:2] - c1[:2]))
    up = world.d.xmat[body].reshape(3, 3)[:, 2]                  # the radio's own z axis in the world
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, float(up[2])))))
    vel = np.zeros(6)
    mujoco.mj_objectVelocity(world.m, world.d, mujoco.mjtObj.mjOBJ_BODY, body, vel, 0)
    print(f"{ITEM} at {np.round(pos, 3).tolist()}, {gap:.3f} m from c1, tilt {tilt:.1f} deg")
    assert gap < NEAR_CASUALTY, f"the radio is {gap:.3f} m from c1"
    assert pos[2] < 0.1, f"the radio is not on the floor (z {pos[2]:.3f})"
    assert tilt < UPRIGHT_DEG, f"the radio lies on its side ({tilt:.1f} deg)"
    assert np.linalg.norm(vel[3:]) < 0.02, "the radio is still moving"
