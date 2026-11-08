"""KIT-ORDER-B1: real B1 observations must precede confirmed supply placement.

The available B1 runner is run_b2.run(floor="B1"), not a rescue runner.
#267 adds the physical Responder and kit but does not drive them or emit
map/casualties or placement receipts. A reached summary is NOT a detection,
and a responder/action command is NOT a confirmed delivery.
"""

import json
import re

import pytest

from tools.run_b2 import run

PLACED = re.compile(
    r"placed (water|first_aid_kit|radio|bandage|splint|thermal_blanket) "
    r"at \[(-?\d+(?:\.\d+)?), (-?\d+(?:\.\d+)?)\]"
)


def first_events(rows):
    """Read bus observations and MuJoCo receipts, attributed by route goal.

    These are the same placement and route-owner contracts used by
    planner.report and planner.paramedic; never infer delivery from a command.
    Kind-only Scout records deliberately contribute neither event.
    """
    located, delivered, routes = {}, {}, {}
    active_route = None
    for row in rows:
        topic, data = row.get("topic"), row.get("data")
        if topic == "map/casualties":
            for casualty in data:
                cid = casualty["id"]
                located[cid] = min(located.get(cid, float("inf")), row["t"])
        elif topic == "route/proposed":
            routes[data["id"]] = data["goal"].rsplit(" to ", 1)[-1]
        elif topic == "log/decision" and data.get("model") == "sim" and data.get("physics") == "mujoco":
            move = re.search(r", move (\S+)$", data.get("perception", ""))
            if move:
                if data["outcome"] in ("act", "done"):
                    active_route = move[1]
                elif data["outcome"] == "refused":
                    active_route = None
            placed = PLACED.fullmatch(data.get("reason", ""))
            if (data["outcome"] == "done" and placed
                    and data.get("perception", "").endswith(f", place_supply {placed[1]}")):
                assert active_route in routes, "confirmed delivery has no casualty route"
                cid = routes[active_route]
                delivered[cid] = min(delivered.get(cid, float("inf")), data["t"])
    return located, delivered


def assert_locate_before_delivery(located, delivered):
    for cid, when in delivered.items():
        assert cid in located, f"{cid}: delivery with no locate"
        assert located[cid] < when, f"{cid}: first locate must be strictly before first delivery"


@pytest.fixture(scope="module")
def real_b1_events(tmp_path_factory):
    _, path = run(seed=0, floor="B1", out_dir=tmp_path_factory.mktemp("kit-order-b1"))
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    summary = next(row for row in rows if row.get("kind") == "summary")
    assert summary["floor"] == "B1"
    assert summary["final_level"] == "B1", "real Scout must actually reach B1"
    return first_events(rows)


def test_real_b1_locate_precedes_each_delivery(real_b1_events):
    assert_locate_before_delivery(*real_b1_events)


@pytest.mark.xfail(strict=True, reason=(
    "KIT-ORDER-B1: after #267 run_b2 --floor B1 still runs only the Scout; "
    "no MuJoCo place_supply completion is emitted (no run_rescue.py on main)"
))
def test_real_b1_has_delivery(real_b1_events):
    _, delivered = real_b1_events
    assert delivered, "real B1 log contains no confirmed supply delivery"


@pytest.mark.parametrize("located, delivered, message", [
    ({"c1": 2.0}, {"c1": 1.0}, "strictly before"),
    ({"c1": 1.0}, {"c1": 1.0}, "strictly before"),
    ({}, {"c1": 1.0}, "no locate"),
    ({"c2": 0.0}, {"c1": 1.0}, "no locate"),
])
def test_checker_rejects_invalid_order(located, delivered, message):
    with pytest.raises(AssertionError, match=message):
        assert_locate_before_delivery(located, delivered)


def test_checker_accepts_locate_then_delivery():
    assert_locate_before_delivery({"c1": 1.0}, {"c1": 2.0})


@pytest.mark.parametrize("locate_t, delivery_t", [(1.0, 2.0), (2.0, 1.0), (None, 2.0)])
def test_bus_receipts_feed_checker(locate_t, delivery_t):
    rows = []
    if locate_t is not None:
        rows.append({"t": locate_t, "topic": "map/casualties", "data": [{"id": "c1"}]})
    rows.extend([
        {"t": 0.0, "topic": "route/proposed", "data": {"id": "r1", "goal": "deliver water to c1"}},
        {"t": 0.0, "topic": "log/decision", "data": {
            "t": 0.0, "model": "sim", "physics": "mujoco", "outcome": "act",
            "perception": "responder at [0, 0], move r1", "reason": "following route r1",
        }},
        {"t": delivery_t, "topic": "log/decision", "data": {
            "t": delivery_t, "model": "sim", "physics": "mujoco", "outcome": "done",
            "perception": "responder at [0, 0], place_supply water", "reason": "placed water at [0.00, 0.00]",
        }},
    ])
    events = first_events(rows)
    assert events[1] == {"c1": delivery_t}
    if locate_t is not None and locate_t < delivery_t:
        assert_locate_before_delivery(*events)
    else:
        with pytest.raises(AssertionError):
            assert_locate_before_delivery(*events)
