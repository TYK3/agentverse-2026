"""DELIVERY-HAS-FLOOR: every delivery in a real run log has a floor.

The run: tools/tests/test_deliver.py's end-to-end delivery (the sim and planner lanes on one bus; the
operator approves the referred gate; the Responder drives route r1 to casualty c1 and sets water down),
recorded by sim.recorder (SIM_RECORD) into a JSONL run log, then read back from that file.

A delivery is a Responder log/decision with outcome "done" for place_supply ("placed <item> at [x, y]").
Its floor is found in the log itself: the responder/action place_supply for that item names its route,
and that route's route/proposed cells end at a level k (perception's grid: k = floor height / RES), which
is one of sim.levels' floors. The log's own sim/truth at the same moment (the Responder's height, RIDE
above its floor) must agree. The decision text does not name the floor itself (it says
"placed water at [1.94, 0.46]"): that is a strict xfail below, so it flips when the Responder adds it.
"""

import asyncio
import copy
import json
import re

import pytest

pytest.importorskip("mujoco")    # a real sim run; CI's tools lane has no MuJoCo (the full job does)

import sim
from perception.levels import k_of
from planner import loop as L
from planner.route import RoutePlanner
from planner.tests.test_loop import Bus, Clock, OffGem
from sim.levels import LEVEL_Z
from tools.tests import test_deliver as deliver

RIDE = 0.05          # the Responder's recorded height above its floor (responder/pose and sim/truth)
TOL = 0.03           # metres either side of a floor
PLACED = re.compile(r"^placed (\w+) at \[(-?[\d.]+), (-?[\d.]+)\]$")


@pytest.fixture(scope="module")
def run_log(tmp_path_factory):
    path = tmp_path_factory.mktemp("delivery-has-floor") / "deliver.jsonl"

    async def go():
        bus, clock = Bus(), Clock()
        world = await sim.start(bus, loop=False)
        world._set_pose((-1.2, -1.7), 0.0)                 # Scout parked out of the Responder's way
        router = RoutePlanner(bus)
        bus.subscribe("map/cells", router.update_map)
        lp = L.Loop(bus, router, gem=OffGem(), clock=clock, review_timeout=5.0).attach()
        await bus.publish("map/cells", deliver.map_from_blocks(bus.of("scene/loaded")[0]["blocks"]))
        await bus.publish("map/hazards", [])
        await bus.publish("map/casualties", [deliver.C1])
        await lp.mission(deliver.cell(*deliver.START), deliver.cell(*deliver.GOAL))
        req = bus.of("gate/request")[0]
        await bus.publish("gate/answer", {"id": req["id"], "approved": True, "by": "operator"})
        r = world.responder
        for n in range(610):                               # at most 60 s, then one to settle
            if n < 600:
                r.step(0.1)
            for topic, data in world.tick(0.1):            # what sim.run publishes each tick
                await bus.publish(topic, data)
            await asyncio.sleep(0)                         # let the Responder's log/decision publishes run
            if n < 600 and r.state != "moving" and not r.queue:
                break
        world.recorder.close()

    with pytest.MonkeyPatch.context() as env:
        env.setenv("SIM_RECORD", str(path))
        asyncio.run(go())
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def deliveries(records):
    return [r for r in records if r["topic"] == "log/decision" and r["data"]["outcome"] == "done"
            and PLACED.match(r["data"]["reason"])]


def floor_at(z):
    """The floor named for height z, or None between floors."""
    return next((name for name, fz in LEVEL_Z.items() if abs(z - fz) <= TOL), None)


def delivery_floor(records, d):
    """The floor a delivery was made on, from its route's cells; checked against the log's sim/truth."""
    item = PLACED.match(d["data"]["reason"])[1]
    actions = [r["data"] for r in records if r["topic"] == "responder/action" and r["t"] <= d["t"]
               and r["data"]["action"] == "place_supply" and r["data"]["item"] == item]
    assert actions, f"no place_supply {item} before the delivery at {d['t']}"
    route_id = actions[-1]["route"]
    routes = [r["data"] for r in records if r["topic"] == "route/proposed" and r["data"]["id"] == route_id]
    assert len(routes) == 1, f"route {route_id} proposed {len(routes)} times"
    cells = routes[0]["cells"]
    assert cells, f"route {route_id} has no cells"
    k = cells[-1][2]
    floors = {name for name, fz in LEVEL_Z.items() if k_of(fz) == k}
    assert len(floors) == 1, f"route {route_id} ends at k {k}, not a floor"
    (floor,) = floors
    truth = [r["data"] for r in records if r["topic"] == "sim/truth" and r["t"] <= d["t"] + 0.1]
    assert truth and truth[-1].get("responder"), "no sim/truth for the Responder at the delivery"
    z = truth[-1]["responder"]["pos"][2] - RIDE
    assert floor_at(z) == floor, f"route says {floor}, the Responder was at floor height {z:.3f}"
    return floor


def assert_deliveries_have_floors(records):
    ds = deliveries(records)
    assert ds, "a real delivery run must deliver"
    return [delivery_floor(records, d) for d in ds]


def test_the_log_is_a_real_recorded_delivery(run_log):
    meta = run_log[0]
    assert meta["topic"] == "record/meta" and meta["data"]["scene"] == "backup"
    assert sum(r["topic"] == "sim/truth" for r in run_log) > 100
    (d,) = deliveries(run_log)
    assert d["data"]["perception"].endswith("place_supply water")


def test_every_delivery_has_a_floor(run_log):
    assert assert_deliveries_have_floors(run_log) == ["ground"]


def test_the_delivery_is_on_its_routes_last_floor_cell(run_log):
    (d,) = deliveries(run_log)
    x, y = (float(v) for v in PLACED.match(d["data"]["reason"]).groups()[1:])
    (route,) = [r["data"] for r in run_log if r["topic"] == "route/proposed"]
    i, j, _ = route["cells"][-1]
    cx, cy = (i + 0.5) * deliver.RES, (j + 0.5) * deliver.RES
    assert ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 < 0.35        # set down just ahead of where it stopped


@pytest.mark.xfail(strict=True, reason="the Responder's delivery decision does not name its floor yet")
def test_the_delivery_record_names_its_floor_itself(run_log):
    for d in deliveries(run_log):
        text = f"{d['data']['perception']} {d['data']['reason']}"
        assert any(re.search(rf"\b{name}\b", text) for name in LEVEL_Z), text


def _mutate(records, mutation):
    if mutation == "no_action":
        return [r for r in records if not (r["topic"] == "responder/action" and r["data"]["action"] == "place_supply")]
    if mutation == "no_route":
        return [r for r in records if r["topic"] != "route/proposed"]
    if mutation == "empty_route":
        next(r for r in records if r["topic"] == "route/proposed")["data"]["cells"] = []
    elif mutation == "between_floors":
        next(r for r in records if r["topic"] == "route/proposed")["data"]["cells"][-1][2] = 5
    elif mutation == "truth_disagrees":
        for r in records:
            if r["topic"] == "sim/truth" and r["data"].get("responder"):
                r["data"]["responder"]["pos"][2] = LEVEL_Z["B1"] + RIDE
    elif mutation == "no_truth":
        return [r for r in records if r["topic"] != "sim/truth"]
    elif mutation == "no_delivery":
        return [r for r in records if r not in deliveries(records)]
    return records


@pytest.mark.parametrize("mutation", ["no_action", "no_route", "empty_route", "between_floors",
                                      "truth_disagrees", "no_truth", "no_delivery"])
def test_broken_logs_cannot_claim_a_floor(run_log, mutation):
    records = copy.deepcopy(run_log)
    assert_deliveries_have_floors(records)
    with pytest.raises(AssertionError):
        assert_deliveries_have_floors(_mutate(records, mutation))
