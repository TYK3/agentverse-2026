"""T11 checks: support rules on synthetic blocks, the backup scene before and after a shake, message shape."""

import asyncio

import pytest

import perception
from perception.hazards import LAYERS, Hazards, risk, risks


def box(id, label, pos, size):
    return {"id": id, "label": label, "pos": list(pos), "size": list(size)}


def test_wall_on_floor_is_stable_and_overhanging_wall_is_at_risk():
    floor_wall = box("b1", "wall", (0, 0, 0.5), (0.05, 0.5, 0.5))
    ledge = box("b2", "rubble", (1.0, 0, 0.05), (0.05, 0.05, 0.05))
    perched = box("b3", "wall", (1.0, 0.3, 0.6), (0.05, 0.4, 0.5))       # base 0.8 m long, 0.1 m on the ledge
    blocks = [floor_wall, ledge, perched]
    assert risk(floor_wall, blocks) is None
    assert risk(perched, blocks).startswith("unsupported wall b3")


def test_rubble_centre_beyond_support_is_at_risk():
    base = box("b1", "rubble", (0, 0, 0.1), (0.1, 0.1, 0.1))
    centred = box("b2", "rubble", (0, 0, 0.25), (0.08, 0.08, 0.05))
    overhang = box("b3", "rubble", (0.2, 0, 0.25), (0.15, 0.08, 0.05))   # centre at x=0.2, support ends at 0.1
    floating = box("b4", "rubble", (2, 2, 0.5), (0.1, 0.1, 0.03))
    blocks = [base, centred, overhang, floating]
    assert risk(centred, blocks) is None
    assert "centre of mass beyond its support" in risk(overhang, blocks)
    assert "nothing beneath" in risk(floating, blocks)


def test_change_marks_moved_collapsed_and_surroundings_at_risk_only():
    a = box("b1", "rubble", (0, 0, 0.05), (0.1, 0.1, 0.05))
    far = box("b2", "rubble", (2, 0, 0.05), (0.1, 0.1, 0.05))
    h = Hazards()
    h.on_scene({"blocks": [a, far]})
    msg = h.on_change({"kind": "aftershock", "t": 3.0, "moved_blocks": ["b1"]})
    assert h.status((0, 0)) == "collapsed"
    assert h.status((4, 0)) == "at_risk" and h.status((-5, 0)) == "at_risk"     # within 0.15 m of b1's box
    assert h.status((5, 0)) == "stable" and h.status((-6, 0)) == "stable"
    assert h.status((40, 0)) == "stable"                                        # b2 keeps its label
    cell = next(m for m in msg if m["cell"][:2] == [0, 0])
    assert cell["why"] == "rubble b1 moved in the aftershock"


def test_message_shape_matches_contract():
    h = Hazards()
    msg = h.on_scene({"blocks": [box("b1", "wall", (0, 0, 0.5), (0.05, 0.05, 0.5))]})
    assert {m["cell"][2] for m in msg} == set(LAYERS)
    for m in msg:
        assert set(m) == {"cell", "status", "why", "estimate"}
        assert m["status"] in ("stable", "at_risk", "collapsed") and m["estimate"] is True
        assert len(m["cell"]) == 3 and all(isinstance(v, int) for v in m["cell"])


# ---- the backup scene (needs mujoco) -------------------------------------------

@pytest.fixture(scope="module")
def backup():
    pytest.importorskip("mujoco")
    from sim import scene
    m, d = scene.load()
    return {"blocks": scene.blocks(m, d)}


def test_backup_scene_flags_what_the_aftershock_moves(backup):
    """#51's shake moves exactly b10 (the slab leaning on b8) and b8; the prediction flags the same two."""
    flagged = risks(backup["blocks"])
    assert set(flagged) == {"b10", "b8"}, flagged
    assert flagged["b8"] == "wall b8 carries leaning rubble b10"


def test_wall_touching_leaning_rubble_is_at_risk():
    wall = box("b1", "wall", (0, 0, 0.5), (0.05, 0.5, 0.5))
    slab = box("b2", "rubble", (-0.3, 0, 0.4), (0.26, 0.2, 0.03))       # nothing beneath, its end on the wall
    other = box("b3", "wall", (-2, 0, 0.5), (0.05, 0.5, 0.5))
    flagged = risks([wall, slab, other])
    assert set(flagged) == {"b1", "b2"}


def test_backup_scene_before_and_after(backup):
    h = Hazards()
    before = h.on_scene(backup)
    slab = [m for m in before if "b10" in m["why"]]
    assert slab and all(m["status"] == "at_risk" for m in slab)
    after = h.on_change({"kind": "aftershock", "t": 3.0, "moved_blocks": ["b10"]})
    assert {m["status"] for m in after if m["why"].startswith("rubble b10 moved")} == {"collapsed"}
    assert any(m["status"] == "at_risk" and m["why"].startswith("next to b10") for m in after)
    assert all(m["estimate"] is True for m in after)


def test_start_publishes_hazards_on_scene_and_change():
    class FakeBus:
        def __init__(self):
            self.subs, self.sent = {}, []

        def subscribe(self, topic, fn):
            self.subs.setdefault(topic, []).append(fn)

        async def publish(self, topic, data):
            self.sent.append((topic, data))
            for fn in self.subs.get(topic, []):
                result = fn(data)
                if asyncio.iscoroutine(result):
                    await result

    async def run():
        bus = FakeBus()
        await perception.start(bus)
        await bus.publish("scene/loaded", {"scene": "backup", "blocks": [box("b1", "rubble", (0, 0, 0.05), (0.1, 0.1, 0.05))]})
        await bus.publish("world/change", {"kind": "aftershock", "t": 1.0, "moved_blocks": ["b1"]})
        for task in list(perception._tasks):
            task.cancel()
        return [d for t, d in bus.sent if t == "map/hazards"]

    before, after = asyncio.run(run())
    assert {m["status"] for m in before} == {"stable"}
    assert "collapsed" in {m["status"] for m in after}
