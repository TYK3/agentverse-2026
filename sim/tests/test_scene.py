"""T03 checks: the backup scene loads, has the required parts, and stays still for 10 s."""

import asyncio
import re

import mujoco
import numpy as np
import pytest

import sim
from sim import scene


@pytest.fixture(scope="module")
def loaded():
    return scene.load()


def test_required_parts(loaded):
    m, _ = loaded
    names = {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i) for i in range(m.nbody)}
    assert {"ground", "casualty_c1"} <= names
    assert m.body_mocapid[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "ground")] >= 0, "ground must be mocap"
    for cam in ("scout_cam", "overview"):
        assert mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, cam) >= 0


def test_blocks_are_labelled(loaded):
    blocks = scene.blocks(*loaded)
    labels = [b["label"] for b in blocks]
    assert all(re.fullmatch(r"b\d+", b["id"]) for b in blocks)
    assert set(labels) == {"wall", "rubble"}
    assert labels.count("wall") >= 8          # outer walls plus two interior walls with openings
    assert 4 <= labels.count("rubble") <= 7        # b16 is a loose board (Y2 found material)


def test_casualty_does_not_collide(loaded):
    m, _ = loaded
    g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "c1_g")
    assert m.geom_contype[g] == 0 and m.geom_conaffinity[g] == 0


def test_stable_for_10_seconds():
    """After a 1 s settle, no block moves more than 1 cm over the next 10 s."""
    m, d = scene.load()
    ids = scene.block_ids(m)
    start = d.xpos[ids].copy()
    for _ in range(int(1.0 / m.opt.timestep)):
        mujoco.mj_step(m, d)
    settled = d.xpos[ids].copy()
    assert np.linalg.norm(settled - start, axis=1).max() < 0.03, "a block moved more than 3 cm while settling"
    for _ in range(int(10.0 / m.opt.timestep)):
        mujoco.mj_step(m, d)
    drift = np.linalg.norm(d.xpos[ids] - settled, axis=1)
    worst = int(drift.argmax())
    assert drift.max() < 0.01, f"block {ids[worst]} drifted {drift.max():.3f} m"


def _check_scene_loaded(payload):
    """Validate against coord/messages.py once T02 lands; until then, check the CONTRACT.md shape."""
    try:
        from coord.messages import TOPICS
    except ImportError:
        assert payload["scene"] in ("backup", "photo")
        for b in payload["blocks"]:
            assert set(b) == {"id", "label", "pos", "size"}
            assert len(b["pos"]) == 3 and len(b["size"]) == 3
            assert all(isinstance(v, float) for v in b["pos"] + b["size"])
        return
    TOPICS["scene/loaded"].model_validate(payload)


def test_start_publishes_scene_loaded():
    class FakeBus:
        def __init__(self):
            self.sent = []

        async def publish(self, topic, data):
            self.sent.append((topic, data))

        def subscribe(self, topic, callback):
            pass

    bus = FakeBus()
    asyncio.run(sim.start(bus, loop=False))
    assert [t for t, _ in bus.sent] == ["scene/loaded"]
    payload = bus.sent[0][1]
    assert payload["scene"] == "backup" and len(payload["blocks"]) == 16
    _check_scene_loaded(payload)


def test_tower_annex_is_a_named_scene():
    """SIM_SCENE=tower_annex resolves to sim/scenes/tower_annex.xml (TOWER-ANNEX-SCENE)."""
    name, path = scene.resolve("tower_annex")
    assert name == "tower_annex" and path.name == "tower_annex.xml" and path.is_file()
