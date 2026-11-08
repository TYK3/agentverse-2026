"""Y8 checks: debris events, pile stability and secondary-fall cells (sim truth, for scoring)."""

import asyncio
import math

import mujoco
import pytest

from sim import debris
from sim.world import World


def settled_world():
    w = World(render=False)
    for _ in range(5):  # let the 5 mm start gaps close so every block rests on something
        w.tick(0.1)
    return w


def names(tr, ids):
    return {tr.names[b] for b in ids}


def test_only_loose_rubble_is_tracked():
    w = settled_world()
    tr = debris.DebrisTracker(w.m)
    live = names(tr, tr.live_ids(w.d))
    assert {"b8", "b10", "b12", "b13", "b15"} <= live
    assert not live & {"plate", "x1", "water", "first_aid_kit", "radio", "scout", "responder", "c1"}


def test_leaning_slab_is_the_one_unstable_pile_before_the_shake():
    w = settled_world()
    tr = debris.DebrisTracker(w.m)
    piles = tr.stacks(w.d)
    unstable = [p for p in piles if p["unstable"]]
    # b10 leans on wall b8: one pile, and exactly the pair the aftershock knocks down.
    assert [p["ids"] for p in unstable] == [["b10", "b8"]]
    assert unstable[0]["worst"] == "b10" and unstable[0]["tilt_deg"] > 20
    walls = [p for p in piles if p["ids"] == ["b7"]]
    assert walls and walls[0]["risk"] < 0.2
    cells = tr.risk_cells(w.d, piles)
    assert cells and all(c["status"] == "at_risk" and c["estimate"] is True for c in cells)
    # b10 sits at about x 1.0, y -0.5: its own column is in the secondary-fall area.
    assert [math.floor(1.0 / debris.RES), math.floor(-0.5 / debris.RES), 0] in [c["cell"] for c in cells]
    assert "b10" in cells[0]["why"]


def test_aftershock_events_moved_fell_settled():
    w = settled_world()
    tr = debris.DebrisTracker(w.m)
    tr.sample(w.d, w.t)
    w.trigger_aftershock()
    events = []
    for _ in range(60):
        w.tick(0.1)
        events += tr.sample(w.d, w.t)
    kinds = {(e["id"], e["kind"]) for e in events}
    assert {("b8", "moved"), ("b8", "fell"), ("b8", "settled"),
            ("b10", "moved"), ("b10", "fell"), ("b10", "settled")} <= kinds
    assert {e["id"] for e in events} == {"b8", "b10"}
    settled = {e["id"]: e for e in events if e["kind"] == "settled"}
    assert settled["b8"]["drop_m"] > debris.FALL_DROP and settled["b8"]["moved_m"] > 0.3
    # Once the rubble is on the floor nothing is left leaning.
    assert not [p for p in tr.stacks(w.d) if p["unstable"]]


STACK = """
<mujoco>
  <option timestep="0.002"/>
  <worldbody>
    <geom name="floor" type="plane" size="3 3 0.1"/>
    <body name="r1" pos="0 0 0.1"><freejoint/><geom type="box" size="0.1 0.1 0.1" density="600"/></body>
    <body name="r2" pos="{x} 0 0.3"><freejoint/><geom type="box" size="0.1 0.1 0.1" density="600"/></body>
  </worldbody>
</mujoco>
"""


def stack(x):
    m = mujoco.MjModel.from_xml_string(STACK.format(x=x))
    d = mujoco.MjData(m)
    for _ in range(50):
        mujoco.mj_step(m, d)
    return m, d


def test_overhanging_stack_scores_higher_than_a_square_one():
    m, d = stack(0.0)
    square = debris.DebrisTracker(m).stacks(d)
    m2, d2 = stack(0.085)
    offset = debris.DebrisTracker(m2).stacks(d2)
    assert [p["ids"] for p in square] == [["r1", "r2"]]
    assert [p["ids"] for p in offset] == [["r1", "r2"]]
    assert offset[0]["worst"] == "r2"
    assert offset[0]["overhang"] > square[0]["overhang"] + 0.4
    assert offset[0]["risk"] > square[0]["risk"]


def test_message_shape():
    w = settled_world()
    tr = debris.DebrisTracker(w.m)
    msg = tr.message(w.d, w.t, [])
    assert set(msg) == {"t", "truth", "events", "stacks"} and msg["truth"] is True
    assert set(msg["stacks"][0]) == {"ids", "risk", "worst", "tilt_deg", "overhang", "motion_m",
                                     "top_z", "min_xy", "max_xy", "unstable"}


@pytest.mark.parametrize("in_contract", [False, True])
def test_attach_publishes_only_once_the_topic_is_in_the_contract(in_contract):
    topics = {"world/change", "world/debris"} if in_contract else {"world/change"}
    sent = []

    class Bus:
        async def publish(self, topic, data):
            sent.append((topic, data))

    async def run():
        w = settled_world()
        debris.attach(w, Bus(), rate_hz=50, topics=topics)
        await asyncio.sleep(0.05)
        w.debris_task.cancel()

    asyncio.run(run())
    assert bool(sent) is in_contract
    if in_contract:
        assert sent[0][0] == "world/debris" and sent[0][1]["truth"] is True
