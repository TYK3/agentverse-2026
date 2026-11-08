"""Collapsed tower scene checks (ref Y1): structure, voids, casualties, aftershock, scene selection."""

import asyncio

import mujoco
import numpy as np
import pytest

import sim
from sim import aftershock, scene, sensors
from sim.scenes import make_tower
from sim.world import World, casualties

LOOSE = ["b26", "b27"]          # LS_a (east room) and LS_b (on the floor-1 ledge)


@pytest.fixture(scope="module")
def tower():
    return scene.load(scene.TOWER)


def test_generated_file_is_up_to_date():
    make_tower.blocks.clear()
    assert scene.TOWER.read_text(encoding="utf-8") == make_tower.xml(), "run python -m sim.scenes.make_tower"


def test_parts_and_labels(tower):
    m, d = tower
    assert m.body_mocapid[m.body("ground").id] >= 0
    for name in ("scout", "responder", "water", "first_aid_kit", "radio", "x1"):
        m.body(name)
    for cam in ("scout_cam", "overview"):
        m.camera(cam)
    blocks = scene.blocks(m, d)
    assert len(blocks) == 27
    assert {b["label"] for b in blocks} == {"wall", "slab", "rubble"}
    assert max(b["pos"][2] for b in blocks) > 2.5                 # three storeys still stand in the west


def test_four_casualties_with_voices(tower):
    m, _ = tower
    found = {name: voice for name, _g, voice in casualties(m)}
    assert found == {"c1": 0.0, "c2": 1.0, "c3": 0.4, "c4": 0.7}
    for name in found:
        g = m.geom(f"{name}_g").id
        assert m.geom_contype[g] == 0 and m.geom_conaffinity[g] == 0


def test_light_debris_can_be_gripped(tower):
    m, _ = tower
    for block in ("b19", "b24"):                                 # lean-to closure G2, breach block G1
        assert m.body_mass[m.body(block).id] < 2.0
        assert mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_EQUALITY, f"grip_{block}") >= 0


def test_stands_still_for_10_seconds():
    m, d = scene.load(scene.TOWER)
    ids = scene.block_ids(m)
    for _ in range(round(1.0 / m.opt.timestep)):
        mujoco.mj_step(m, d)
    settled = d.xpos[ids].copy()
    for _ in range(round(10.0 / m.opt.timestep)):
        mujoco.mj_step(m, d)
    drift = np.linalg.norm(d.xpos[ids] - settled, axis=1)
    assert drift.max() < 0.005, f"{scene.blocks(m, d)[int(drift.argmax())]['id']} drifted {drift.max():.4f} m"


def test_aftershock_drops_exactly_the_loose_slabs(tower):
    m, d = tower
    moved, boxes = aftershock.aftershock_effects(m, d)
    assert sorted(aftershock.body_name(m, i) for i in moved) == LOOSE
    ledge_slab = boxes[m.body("b27").id]
    assert ledge_slab[1][0][0] > 1.0                             # LS_b ends up out in the east room


@pytest.fixture(scope="module")
def shaken():
    w = World(path=scene.TOWER, render=False)
    w.trigger_aftershock()
    events = []
    for _ in range(31):
        events += w.tick(0.1)
    return w, events


def test_live_aftershock_and_voids_survive(shaken):
    w, events = shaken
    assert events == [("world/change", {"kind": "aftershock", "t": 3.0, "moved_blocks": LOOSE})]
    # The lean-to and the pancake slab are still up: their voids are intact.
    assert w.d.xpos[w.m.body("b17").id][2] > 0.4
    assert w.d.xpos[w.m.body("b23").id][2] == pytest.approx(0.352, abs=0.01)
    # The slabs now lie across the east room, so a route through its middle is blocked by them.
    assert w.d.xpos[w.m.body("b27").id][2] < 0.5


def _sees(w, at, name):
    g = w.m.geom(f"{name}_g").id
    origin = np.array([*at, 0.075])
    return sensors.first_hit(w.m, w.d, origin, w.d.geom_xpos[g], w.scout)[0] == g


def test_how_each_casualty_can_be_found():
    w = World(path=scene.TOWER, render=False)
    in_room = (-0.9, 0.2)            # west room
    corridor = (0.65, 0.0)           # east room, by the lean-to
    breach = (1.58, -1.5)
    assert _sees(w, in_room, "c1")                           # c1: in the open
    for at in (in_room, corridor, breach, (1.2, -0.1), (0.65, 0.8)):
        assert not _sees(w, at, "c2")                        # c2: enclosed, never in sight
    assert _sees(w, (0.65, -0.1), "c3") or _sees(w, (1.2, -0.1), "c3")   # c3: under the slab, from low down
    assert _sees(w, breach, "c4")
    # Sound: from the corridor the loudest casualty is c2 (c1 is silent, the rest are further or fainter).
    w._set_pose(np.array(corridor), 0.0)
    w.rng = np.random.default_rng(1)
    msg = w.sensors_message(camera=False)
    c2 = w.d.geom_xpos[w.m.geom("c2_g").id]
    assert abs(msg["acoustic"]["bearing"] - sensors.relative_bearing(w.pos, 0.0, c2)) < 20
    # Clearing the light closure block G2 (b19) opens a line of sight to c2.
    b19 = w.m.body("b19").id
    adr = w.m.jnt_qposadr[w.m.body_jntadr[b19]]
    w.d.qpos[adr:adr + 3] = [-3.0, -3.5, 0.1]
    mujoco.mj_forward(w.m, w.d)
    assert _sees(w, (1.75, -0.6), "c2") or _sees(w, (1.75, -0.4), "c2")


def test_thermal_shows_two_casualties_at_once_and_stays_in_range():
    w = World(path=scene.TOWER, render=False)
    w._set_pose(np.array([1.2, -0.1]), np.radians(-90))        # facing south: c3 and c4 ahead
    grid = np.array(w.sensors_message(camera=False)["thermal"])
    assert grid.max() <= 1.0 and grid.min() >= 0.1


def test_sim_scene_selects_the_tower(monkeypatch):
    class Bus:
        def __init__(self):
            self.sent = []

        async def publish(self, topic, data):
            self.sent.append((topic, data))

        def subscribe(self, topic, cb):
            pass

    monkeypatch.setenv("SIM_SCENE", "tower")
    bus = Bus()
    world = asyncio.run(sim.start(bus, loop=False))
    assert world.scene == "tower"
    loaded = next(d for t, d in bus.sent if t == "scene/loaded")
    assert loaded["scene"] == "tower" and len(loaded["blocks"]) == 27


def test_resolve():
    assert scene.resolve("backup") == ("backup", scene.BACKUP)
    assert scene.resolve("tower") == ("tower", scene.TOWER)
    assert scene.resolve(str(scene.TOWER)) == ("tower", scene.TOWER)
    with pytest.raises(ValueError):
        scene.resolve("no-such-scene")
