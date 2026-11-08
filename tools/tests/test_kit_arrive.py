"""KIT-ARRIVE: every item of the Responder's kit arrives at casualty c1 and stays there, in a real sim run.

The Responder (sim/responder.py) drives the scripted T06 run in the backup scene (sim.demo_responder:
breach, room 1, clear b11, the room 2/3 gap, up to c1, place the water). Then it places every other item
it carries (first aid kit, radio, bandage, splint, thermal blanket) with real place_supply actions, and the
physics settles. Each action and every item's final pose go to a jsonl log, which is read back. Checks:
  - each item was loaded, placed by the Responder ("placed <item> at [x, y]") and is no longer held;
  - after settling, every item is within NEAR of c1, at rest, and not below the floor.

Finding (strict xfail below): the Responder puts every item down at the same spot ahead of it, so later
items land on earlier ones; the water placed first is shoved about 0.6 m (still within NEAR of c1 today).
When placement uses separate spots, that test starts passing and must be turned into a plain test.
"""

import json
import math

import pytest

pytest.importorskip("mujoco")

NEAR = 0.5            # metres from c1 that count as delivered (the e2e runners' rule)
SETTLE = 3.0          # sim seconds of physics after the last placement
AT_REST = 0.02        # m/s
SHOVE = 0.3           # metres an already-placed item may be pushed by later placements
LATER = ("first_aid_kit", "radio", "bandage", "splint", "thermal_blanket")


@pytest.fixture(scope="module")
def delivery(tmp_path_factory):
    import numpy as np

    from sim import demo_responder
    from sim import responder as R
    from sim.world import World

    w, r = demo_responder.run(world=World(render=False))
    records = []

    def pos(name):
        return [round(float(v), 3) for v in w.d.xpos[w.m.body(name).id]]

    records.append({"t": round(w.t, 2), "kind": "after_script", "responder": pos("responder"),
                    "state": r.state, "water": pos("water")})
    for item in LATER:
        out = r.on_action({"action": "place_supply", "route": "r2", "item": item})
        records.append({"t": round(w.t, 2), "kind": "action", "item": item, "outcome": out.get("outcome"),
                        "reason": out.get("reason", ""), "held_after": r.holding(item), "water": pos("water")})
        for _ in range(20):
            r.step(0.1)
            w.tick(0.1)
    for _ in range(round(SETTLE / 0.1)):
        r.step(0.1)
        w.tick(0.1)
    c1 = [round(float(v), 3) for v in w.d.geom_xpos[w.casualty_geom]]
    for item in R.SUPPLIES:
        b = w.m.body(item).id
        speed = float(np.linalg.norm(w.d.cvel[b][3:]))
        records.append({"t": round(w.t, 2), "kind": "final", "item": item, "pos": pos(item),
                        "speed": round(speed, 4), "held": r.holding(item)})
    records.append({"t": round(w.t, 2), "kind": "casualty", "id": "c1", "pos": c1})
    path = tmp_path_factory.mktemp("kit") / "kit-arrive.jsonl"
    path.write_text("".join(json.dumps(x) + "\n" for x in records), encoding="utf-8")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def final(log):
    c1 = next(x for x in log if x["kind"] == "casualty")["pos"]
    return c1, {x["item"]: x for x in log if x["kind"] == "final"}


def test_the_responder_reaches_c1_and_places_the_water(delivery):
    first = delivery[0]
    assert first["state"] == "arrived"
    _, items = final(delivery)
    assert not items["water"]["held"]


def test_every_other_item_is_placed_by_the_responder(delivery):
    actions = {x["item"]: x for x in delivery if x["kind"] == "action"}
    for item in LATER:
        a = actions[item]
        assert a["outcome"] == "done" and a["reason"].startswith(f"placed {item} at"), a
        assert a["held_after"] is False


def test_the_whole_kit_arrives_at_c1_and_stays(delivery):
    c1, items = final(delivery)
    assert set(items) == {"water", *LATER}
    for name, x in items.items():
        assert not x["held"], f"{name} still on the Responder"
        assert math.dist(x["pos"][:2], c1[:2]) <= NEAR, f"{name} at {x['pos']}, c1 at {c1}"
        assert x["speed"] < AT_REST, f"{name} still moving at {x['speed']} m/s"
        assert x["pos"][2] > -0.003, f"{name} below the floor at z {x['pos'][2]}"


@pytest.mark.xfail(strict=True, reason="all items are placed at one spot, so later ones shove the water ~0.6 m")
def test_later_placements_do_not_shove_the_water(delivery):
    placed = delivery[0]["water"]
    _, items = final(delivery)
    assert math.dist(placed[:2], items["water"]["pos"][:2]) <= SHOVE
