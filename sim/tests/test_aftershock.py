"""T05 checks: the aftershock fails the leaning slab, the route check uses it, inject drops a block."""

import asyncio
import math
import time

import numpy as np
import pytest

import sim
from sim import aftershock, inject, scene
from sim.world import World


def cell(x, y, k=0):
    return [math.floor(x / aftershock.RES), math.floor(y / aftershock.RES), k]


ROOM2_SLAB = [cell(0.95, -0.5), cell(0.9, -0.45)]      # beside the leaning slab b10
ROOM1 = [cell(-1.0, 0.25), cell(-0.9, 0.25), cell(-0.8, 0.25)]


@pytest.fixture(scope="module")
def world():
    return World(render=False)


def test_leaning_slab_moves_and_flat_rubble_does_not():
    m, d = scene.load()
    moved, _ = aftershock.aftershock_effects(m, d)
    names = [aftershock.body_name(m, i) for i in moved]
    assert "b10" in names                                   # the slab leaning on b8
    assert "b14" not in names and "b12" not in names        # flat on the floor
    assert not {"b1", "b2", "b3", "b4", "b5"} & set(names)  # the braced outer shell stands


def test_effects_never_touch_the_live_world():
    m, d = scene.load()
    before = d.qpos.copy(), d.time
    aftershock.aftershock_effects(m, d)
    assert np.array_equal(d.qpos, before[0]) and d.time == before[1]


def test_verify_rejects_route_by_the_slab_and_accepts_room_1(world):
    bad = world.verify({"id": "r1", "cells": ROOM1 + ROOM2_SLAB})
    assert bad["ok"] is False and bad["id"] == "r1"
    assert bad["unstable_cells"] == ROOM2_SLAB
    assert "b10" in bad["detail"]
    good = world.verify({"id": "r2", "cells": ROOM1})
    assert good == {"id": "r2", "ok": True, "unstable_cells": [], "detail": good["detail"]}


def test_layer_does_not_matter(world):
    """Planner routes on k=0, perception maps on k=1: both must give the same answer."""
    k1 = [[i, j, 1] for i, j, _ in ROOM2_SLAB]
    assert world.verify({"id": "r", "cells": k1})["ok"] is False


def test_same_inputs_same_answer():
    m, d = scene.load()
    a, b = aftershock.unstable_xy(m, d), aftershock.unstable_xy(m, d)
    assert a == b


def test_live_aftershock_publishes_world_change_then_route_is_clear():
    w = World(render=False)
    assert w.trigger_aftershock() and w.shaking
    assert not w.trigger_aftershock()                        # one at a time
    events = []
    for _ in range(35):
        events += w.tick(0.1)
    assert not w.shaking
    assert events == [("world/change", {"kind": "aftershock", "t": 3.0, "moved_blocks": ["b8", "b10"]})]
    assert w.d.mocap_pos[w.ground].tolist() == w.ground_base.tolist()
    # The slab is down now: a second aftershock moves nothing, so the slab route is verified.
    assert w.verify({"id": "r", "cells": ROOM2_SLAB})["ok"] is True


def test_inject_drops_a_block_and_reports_it():
    w = World(render=False)
    status, body = inject.handle(w, {"kind": "block_added", "pos": [-0.9, 0.25, 0.3]})
    assert (status, body) == (200, {"ok": True, "block": "x1"})
    events = []
    for _ in range(12):
        events += w.tick(0.1)
    assert events == [("world/change", {"kind": "block_added", "t": 1.0, "moved_blocks": ["x1"]})]
    x1 = w.m.body("x1").id
    assert abs(w.d.xpos[x1][2] - 0.08) < 0.01              # it fell and rests on the floor
    assert w.verify({"id": "r", "cells": ROOM1})["ok"] is True   # it sits flat, so it is not unstable
    lidar = w.sensors_message(camera=False)["lidar"]
    assert min(lidar) < 6.0
    assert inject.handle(w, {"kind": "block_added", "pos": [0, 0, 0.1]})[0] == 409    # only one spare
    assert inject.handle(w, {"kind": "block_added"})[0] == 400
    assert inject.handle(w, {"kind": "flood"})[0] == 400


def test_spare_block_is_not_in_scene_loaded():
    m, d = scene.load()
    assert [b["id"] for b in scene.blocks(m, d)] == [f"b{i}" for i in range(1, 16)]
    assert m.geom_contype[m.geom("x1_rubble").id] == 0


def test_start_answers_route_proposed_within_1s():
    class Bus:
        def __init__(self):
            self.sent, self.subs = [], {}

        async def publish(self, topic, data):
            self.sent.append((time.monotonic(), topic, data))
            for cb in self.subs.get(topic, []):
                await cb(data) if asyncio.iscoroutinefunction(cb) else cb(data)

        def subscribe(self, topic, cb):
            self.subs.setdefault(topic, []).append(cb)

    async def main():
        bus = Bus()
        world = await sim.start(bus, loop=False)
        sent_at = time.monotonic()
        await bus.publish("route/proposed", {"id": "r3", "robot": "responder", "cells": ROOM2_SLAB,
                                             "goal": "deliver water to c1", "model": "local-astar"})
        return bus, world, sent_at

    bus, _, sent_at = asyncio.run(main())
    answers = [(t, d) for t, topic, d in bus.sent if topic == "route/verified"]
    assert len(answers) == 1
    t, data = answers[0]
    assert t - sent_at < 1.0
    assert data["id"] == "r3" and data["ok"] is False


def test_inject_install_is_a_no_op_outside_the_hub(world):
    import sys

    assert "coord.hub" not in sys.modules
    assert inject.install(world) is False


def test_shake_offset():
    assert aftershock.shake_offset(-0.1) == [0.0, 0.0, 0.0]
    assert aftershock.shake_offset(1 / 16)[0] == pytest.approx(aftershock.AMPLITUDE)
    assert aftershock.shake_offset(aftershock.SHAKE) == [0.0, 0.0, 0.0]
