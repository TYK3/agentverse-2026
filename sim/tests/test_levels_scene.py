"""LEVELS-SCENE: sim.levels.start() announces the multi-level scene as scene/loaded "levels" (coord/CONTRACT.md
SCENE-B2), with the world's own blocks unchanged, and listens for scout/goto."""

import asyncio

from sim import levels, scene


class FakeBus:
    def __init__(self):
        self.sent, self.subs = [], {}

    def subscribe(self, topic, fn):
        self.subs.setdefault(topic, []).append(fn)

    async def publish(self, topic, payload):
        self.sent.append((topic, payload))


def started():
    bus = FakeBus()
    world = asyncio.run(levels.start(bus, loop=False))
    return bus, world


def test_start_publishes_scene_levels():
    bus, _ = started()
    loaded = [p for t, p in bus.sent if t == "scene/loaded"]
    assert len(loaded) == 1
    assert loaded[0]["scene"] == "levels"
    try:                                       # the sim CI job has no pydantic: check the CONTRACT.md shape
        from coord.messages import validate_payload
    except ImportError:
        assert all(set(b) == {"id", "label", "pos", "size"} for b in loaded[0]["blocks"])
    else:
        assert validate_payload("scene/loaded", loaded[0]) == loaded[0]


def test_start_publishes_the_worlds_own_blocks_unchanged():
    bus, world = started()
    loaded = next(p for t, p in bus.sent if t == "scene/loaded")
    assert isinstance(world, levels.LevelWorld)
    assert loaded["blocks"] == scene.blocks(world.m, world.d)   # levels are static geoms: no b<n> blocks yet


def test_start_listens_for_scout_goto():
    bus, world = started()
    assert bus.subs["scout/goto"] == [world.goto]
