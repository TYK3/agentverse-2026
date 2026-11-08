"""KIT-AT-CASUALTY: the first aid kit reaches casualty c1 through the real planner and sim (ref KIT-AT-CASUALTY).

The same real-lane run as tools/tests/test_deliver.py (whose helpers it imports, unchanged): the sim
(sim.start, loop=False: MuJoCo world, physics check, Responder) and the planner loop (router, physics
verify, gate, dispatch) on one in-process bus, GEMINI_MODE off, the world ticked by hand in sim time.
The mission asks for item "first_aid_kit"; the operator approves the gate; the planner dispatches move,
place_supply and release of the kit; the sim's Responder carries them out with real MuJoCo bodies.

Checked: nothing moves before approval; the dispatched actions name the kit, not water; the Responder
arrives, is never refused or blocked, places the kit and no longer carries it, but still carries the
rest of its load (only what was asked for leaves the deck); the kit ends on the floor within
NEAR_CASUALTY of c1, at rest.
"""

import asyncio

import pytest

pytest.importorskip("mujoco")

import numpy as np

import sim
from planner import loop as L
from planner.route import RoutePlanner
from planner.tests.test_loop import Bus, Clock, OffGem
from tools.tests.test_deliver import C1, GOAL, START, cell, map_from_blocks

ITEM = "first_aid_kit"
NEAR_CASUALTY = 0.6                # metres, as test_deliver's water check


def deliver(item):
    """Run the real delivery of `item` to c1. Returns (world, responder, route id, bus)."""
    async def run():
        bus, clock = Bus(), Clock()
        world = await sim.start(bus, loop=False)
        world._set_pose((-1.2, -1.7), 0.0)          # Scout parked out of the Responder's way
        router = RoutePlanner(bus)
        bus.subscribe("map/cells", router.update_map)
        lp = L.Loop(bus, router, gem=OffGem(), clock=clock, review_timeout=5.0).attach()
        await bus.publish("map/cells", map_from_blocks(bus.of("scene/loaded")[0]["blocks"]))
        await bus.publish("map/hazards", [])
        await bus.publish("map/casualties", [C1])
        await lp.mission(cell(*START), cell(*GOAL), goal_text=f"deliver {item} to c1", item=item)
        (route,) = bus.of("route/proposed")
        (req,) = bus.of("gate/request")
        assert bus.of("responder/action") == [], "something moved before the operator answered"
        await bus.publish("gate/answer", {"id": req["id"], "approved": True, "by": "operator"})
        r = world.responder
        for _ in range(600):                         # at most 60 s of sim time
            r.step(0.1)
            world.tick(0.1)
            await asyncio.sleep(0)
            if r.state != "moving" and not r.queue:
                break
        for _ in range(10):                          # one second for the item to settle
            world.tick(0.1)
        return world, r, route["id"], bus

    return asyncio.run(run())


@pytest.fixture(scope="module")
def run():
    return deliver(ITEM)


def test_the_planner_dispatches_the_kit_not_water(run):
    _world, _r, rid, bus = run
    assert [(a["action"], a["route"], a["item"]) for a in bus.of("responder/action")] == [
        ("move", rid, ITEM), ("place_supply", rid, ITEM), ("release", rid, ITEM)]


def test_the_responder_arrives_and_places_the_kit(run):
    _world, r, rid, _bus = run
    outcomes = [e["outcome"] for e in r.log]
    assert "refused" not in outcomes and "blocked" not in outcomes, r.log
    assert r.state == "arrived"
    done = [(e["perception"].split("], ")[-1], e["reason"]) for e in r.log if e["outcome"] == "done"]
    assert [p for p, _ in done] == [f"move {rid}", f"place_supply {ITEM}", f"release {ITEM}"], r.log
    assert done[1][1].startswith(f"placed {ITEM} at ")
    carrying = r.status()["carrying"]
    assert ITEM not in carrying and "water" in carrying          # only what was asked for left the deck


def test_the_kit_is_on_the_floor_beside_c1_and_at_rest(run):
    world, _r, _rid, _bus = run
    kit = world.m.body(ITEM).id
    pos = world.d.xpos[kit]
    c1 = world.d.xpos[world.m.body("casualty_c1").id]
    gap = float(np.linalg.norm(pos[:2] - c1[:2]))
    print(f"{ITEM} at {np.round(pos, 3).tolist()}, {gap:.3f} m from c1")
    assert gap < NEAR_CASUALTY, f"{ITEM} is {gap:.3f} m from c1"
    assert pos[2] < 0.1, f"{ITEM} is not on the floor (z {pos[2]:.3f})"
    vel = np.zeros(6)
    import mujoco

    mujoco.mj_objectVelocity(world.m, world.d, mujoco.mjtObj.mjOBJ_BODY, kit, vel, 0)
    assert np.linalg.norm(vel[3:]) < 0.02, "the kit is still moving"
