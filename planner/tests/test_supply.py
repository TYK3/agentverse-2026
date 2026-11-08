"""Y2 checks: the planner picks a kit item or found material from a casualty's injuries, finds a board
in the Scout's own depth points, and the handoff fetches the board before carrying it to the casualty."""

import asyncio

import pytest

from planner import supply as S

FULL = set(S.KIT)


def plank(cx, cy, length=0.4, width=0.06, height=0.04, step=0.01, along_y=True):
    """Depth points on the top face of a plank lying on the floor (what a camera sees from above)."""
    pts = []
    n_len, n_wid = int(length / step) + 1, int(width / step) + 1
    for a in range(n_len):
        for b in range(n_wid):
            u, v = -length / 2 + a * step, -width / 2 + b * step
            x, y = (cx + v, cy + u) if along_y else (cx + u, cy + v)
            pts.append([x, y, height])
    return pts


def wall(x, y0, y1, top=1.0, step=0.02):
    return [[x, y0 + k * step, z] for k in range(int((y1 - y0) / step) + 1) for z in (0.05, 0.3, top)]


SCENE = {"scene": "backup", "blocks": [{"id": "b16", "label": "rubble", "pos": [2.25, 0.1, 0.02], "size": [0.03, 0.2, 0.02]},
                                       {"id": "b2", "label": "wall", "pos": [2.5, 0.25, 0.5], "size": [0.05, 1.3, 0.5]}]}


# ---- choose ------------------------------------------------------------------------------------------

def test_injury_maps_to_the_kit_item_that_treats_it():
    assert S.choose(["bleeding from the left arm"], FULL)["item"] == "bandage"
    assert S.choose(["I think my leg is broken"], FULL)["item"] == "splint"
    assert S.choose(["shivering, very cold"], FULL)["item"] == "thermal_blanket"
    assert S.choose(["so thirsty"], FULL)["item"] == "water"
    assert S.choose(["burn on hand"], FULL)["item"] == "first_aid_kit"
    assert S.choose([{"type": "fracture", "site": "shin"}], FULL)["item"] == "splint"   # Y3 dict entries


def test_most_urgent_need_first_and_unknown_stays_unknown():
    got = S.choose(["broken wrist", "bleeding scalp"], FULL)
    assert got["item"] == "bandage" and got["source"] == "kit"
    assert S.choose([], FULL) is None
    assert S.choose(["fine, just stuck"], FULL) is None


def test_fracture_without_kit_splint_uses_a_found_board_else_the_first_aid_kit():
    board = {"block": "b16", "pos": [2.25, 0.1, 0.02], "length": 0.45, "width": 0.1, "kg": 0.36}
    got = S.choose(["fractured forearm"], FULL - {"splint"}, board)
    assert got == {"item": "splint", "block": "b16", "need": "fracture", "source": "found", "why": got["why"]}
    assert "found board b16" in got["why"] and "0.36 kg" in got["why"]
    fallback = S.choose(["fractured forearm"], FULL - {"splint"}, None)
    assert fallback["item"] == "first_aid_kit" and fallback["source"] == "fallback"
    assert S.choose(["fractured forearm"], set(), None) is None
    # a kit splint is still preferred over found material
    assert S.choose(["fractured forearm"], FULL, board)["source"] == "kit"


# ---- BoardFinder --------------------------------------------------------------------------------------

def test_finds_a_board_from_depth_points_and_names_it():
    f = S.BoardFinder()
    f.on_scene(SCENE)
    f.on_sensors({"points": plank(2.25, 0.1) + [[1.0, 1.0, 0.01]] * 20})   # floor points ignored
    boards = f.boards()
    assert len(boards) == 1
    b = boards[0]
    assert b["block"] == "b16"
    assert 0.3 <= b["length"] <= 0.5 and b["width"] <= S.WIDTH_M
    assert abs(b["pos"][0] - 2.25) < 0.05 and abs(b["pos"][1] - 0.1) < 0.05
    assert 0.2 < b["kg"] <= S.ARM_PAYLOAD_KG, "estimated from sensed volume, liftable"
    assert f.best(near=(2.0, 1.0))["block"] == "b16"


def test_low_points_at_a_wall_foot_short_bits_and_heavy_beams_are_not_boards():
    f = S.BoardFinder()
    f.on_scene(SCENE)
    f.add(plank(2.42, 0.1) + wall(2.46, -0.2, 0.4))          # pressed against a wall: part of the wall/pile
    f.add(plank(1.0, 1.0, length=0.15))                      # too short to splint
    f.add(plank(0.0, 0.0, length=0.6, width=0.1, height=0.09))   # long, but a heavy beam
    assert all(b["kg"] > S.ARM_PAYLOAD_KG for b in f.boards())
    assert f.best() is None


def test_unnamed_or_taken_board_is_not_offered():
    f = S.BoardFinder()
    f.add(plank(1.0, 1.0))                                   # no scene/loaded block near it
    assert f.boards() and f.best() is None
    f.on_scene({"blocks": [{"id": "b9", "pos": [1.0, 1.0, 0.02]}]})
    assert f.best()["block"] == "b9"
    f.taken.add("b9")
    assert f.best() is None


# ---- handoff: fetch the board, then carry it to the casualty -----------------------------------------

pytest.importorskip("pydantic")
pytest.importorskip("fastapi")

from planner.tests.test_handoff import RES, World, casualty, sim_log


def run(coro):
    return asyncio.run(coro)


def test_handoff_brings_the_item_the_injury_needs():
    async def go():
        w = await World().start()
        w.handoff.on_triage({"id": "c1", "injuries": ["deep cut, bleeding"]})
        await w.bus.publish("map/casualties", [casualty(confidence=0.9)])
        return w

    w = run(go())
    acts = w.topics("responder/action")
    assert [a["action"] for a in acts] == ["move", "place_supply", "release"]
    assert {a["item"] for a in acts} == {"bandage"} and all("block" not in a or a["block"] is None for a in acts)
    assert any("bleeding: kit bandage" in d["reason"] for d in w.handoff_logs("handoff"))


def test_handoff_fetches_a_found_board_when_the_kit_splint_is_gone():
    async def go():
        w = await World().start()
        h = w.handoff
        h.kit.discard("splint")
        await w.bus.publish("scene/loaded", {"scene": "backup", "blocks": [
            {"id": "b16", "label": "rubble", "pos": [1.0, 0.5, 0.02], "size": [0.03, 0.2, 0.02]}]})
        h.finder.add(plank(1.0, 0.5))
        h.on_triage({"id": "c1", "injuries": ["broken shin"], "recommended_action": "splint the leg"})
        await w.bus.publish("map/casualties", [casualty(confidence=0.9)])
        fetch = list(w.topics("responder/action"))
        fetch_route = w.topics("route/proposed")[-1]
        await w.bus.publish("log/decision", sim_log("done", "gripped b16 (0.4 kg)", at=(1.0, 0.25)))
        after_grip = list(w.topics("responder/action"))[len(fetch):]
        await w.bus.publish("log/decision", sim_log("done", "placed b16 as a splint at [1.50, 1.30]", at=(1.5, 1.1)))
        return w, fetch, fetch_route, after_grip

    w, fetch, fetch_route, after_grip = run(go())
    assert [(a["action"], a.get("block")) for a in fetch] == [("move", None), ("grip", "b16")]
    gx, gy, _ = fetch_route["cells"][-1]
    assert ((gx + 0.5) * RES - 1.0) ** 2 + ((gy + 0.5) * RES - 0.5) ** 2 <= 0.35 ** 2, "stops within reach of the board"
    assert [(a["action"], a.get("block")) for a in after_grip] == [("move", None), ("place_supply", "b16"), ("release", "b16")]
    assert {a["item"] for a in fetch + after_grip} == {"splint"}
    h = w.handoff
    assert h.served == {"c1"} and h.active is None and h.holding_block is None
    assert "b16" in h.finder.taken and "splint" not in h.kit


def test_what_the_casualty_said_brings_a_second_delivery():
    """G3 -> Y2: water goes first; when the casualty tells the robot their leg is broken, a splint follows."""
    async def go():
        w = await World().start()
        await w.bus.publish("map/casualties", [casualty(confidence=0.9)])
        await w.bus.publish("log/decision", sim_log("done", "placed water at [1.50, 1.30]", at=(1.5, 1.1)))
        assert w.handoff.served == {"c1"}
        before = len(w.topics("responder/action"))
        contact = {"id": "c1", "t": 30, "status": "talking", "turns": 3, "max_turns": 8,
                   "facts": {"responsive": True, "hurt": ["leg"], "can_move": False},
                   "injuries": ["Yes, my left leg. I think it's broken."], "receipts": []}
        await w.bus.publish("casualty/contact", contact)
        assert len(w.topics("responder/action")) == before, "no new mission while still talking"
        await w.bus.publish("casualty/contact", {**contact, "status": "done", "t": 45})
        return w, w.topics("responder/action")[before:]

    w, second = run(go())
    assert [a["action"] for a in second] == ["move", "place_supply", "release"]
    assert {a["item"] for a in second} == {"splint"}
    assert w.handoff.active == "c1" and "c1" not in w.handoff.served
    assert any(d["outcome"] == "requeued" and "splint" in d["reason"] for d in w.handoff_logs())
