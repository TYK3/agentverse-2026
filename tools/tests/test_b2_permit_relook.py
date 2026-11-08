"""PERMIT-RELOOK-B2: after a slab shift on B2, move permission returns only from a fresh observation.

A real B2 rescue (tools/run_b2.py --floor B2, seed 0: the Scout's closed-loop descent, a slab dropped on its
route to c2, the stop and the recheck) runs with the real L1 permit rule (planner.permit.Permits) beside
it, fed only what the robots have:
  - every route the Scout plans on B2 is proposed to Permits and marked verified (the levels scene has no
    physics route check yet, so "verified" here is given, not computed);
  - every sensors/scout frame the sim produces goes to Permits.on_sensors, so a permit is revoked by a
    LiDAR hit inside its route (a sensed shift) and re-earned only when every route cell is seen free by
    LiDAR again (a fresh scan). There is no timer.
Each permit/route message is logged to jsonl with the run's shift record, read back, and checked:
  - the route the slab landed on had a permit, and lost it to a sensed shift within 2 s of the drop;
  - that route is never granted again while the slab is on it (no grant by time);
  - every grant after the shift is either a fresh scan or a new route planned from the fresh map, and
    no granted route crosses the slab.
"""

import json

import pytest

pytest.importorskip("mujoco")

B2_K = -24
REVOKE_WITHIN = 2.0     # sim seconds from the drop to the revocation


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def run_log(tmp_path_factory, monkeypatch_module):
    import planner.levels as planner_levels
    from planner.permit import Permits
    from sim import levels
    from tools.run_b2 import run

    permits = Permits()
    clock = {"t": 0.0}
    out = []
    n = {"route": 0}

    def note(pairs):
        for topic, payload in pairs:
            if topic == "permit/route":
                out.append({"t": clock["t"], "kind": "permit", **payload})

    original_route = planner_levels.find_route

    def find_route(snapshot, hazards, start, goal):
        plan = original_route(snapshot, hazards, start, goal)
        if start[2] == B2_K and plan["status"] in ("ok", "explore") and len(plan["cells"]) > 2:
            n["route"] += 1
            rid = f"b2r{n['route']}"
            permits.on_route_proposed({"id": rid, "cells": plan["cells"]})
            note(permits.on_route_verified({"id": rid, "ok": True, "detail": "given"}, clock["t"]))
            out.append({"t": clock["t"], "kind": "route", "id": rid, "cells": [c[:2] for c in plan["cells"]]})
        return plan

    original_sensors = levels.LevelWorld.sensors_message

    def sensors(self, camera=True):
        data = original_sensors(self, camera=camera)
        clock["t"] = round(self.t, 2)
        note(permits.on_sensors(data, clock["t"]))
        return data

    monkeypatch_module.setattr(planner_levels, "find_route", find_route)
    monkeypatch_module.setattr(levels.LevelWorld, "sensors_message", sensors)
    d = tmp_path_factory.mktemp("relook")
    verdict, path = run(seed=0, out_dir=d, floor="B2")
    shift = next(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                 if json.loads(line)["kind"] == "shift")
    log = d / "b2-permit-relook.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in [shift, *out]), encoding="utf-8")
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return verdict, records


def split(records):
    shift = records[0]
    routes = {r["id"]: r for r in records if r["kind"] == "route"}
    permits = [r for r in records if r["kind"] == "permit"]
    core = {tuple(c) for c in shift["core"]}
    return shift, routes, permits, core


def shifted_route(records):
    """The route whose permit the slab revoked: granted before the drop, and its cells cross the slab."""
    shift, routes, permits, core = split(records)
    granted = [p["route"] for p in permits if p["granted"] and p["t"] <= shift["t"]]
    on = [rid for rid in granted if core & {tuple(c) for c in routes[rid]["cells"]}]
    return on[-1] if on else None


def test_the_rescue_itself_passes(run_log):
    verdict, _ = run_log
    assert verdict["failed"] == [], verdict["steps"]


def test_the_route_under_the_slab_loses_its_permit_to_a_sensed_shift(run_log):
    _, records = run_log
    shift, _, permits, _ = split(records)
    rid = shifted_route(records)
    assert rid is not None, "no granted route crossed the slab when it landed"
    revoked = next((p for p in permits if p["route"] == rid and not p["granted"] and p["t"] >= shift["t"]), None)
    assert revoked is not None, f"{rid} kept its permit after the slab landed on it"
    assert revoked["t"] - shift["t"] <= REVOKE_WITHIN
    assert revoked["evidence"][-1]["kind"] == "shift", revoked["reason"]       # sensed by LiDAR, not told


def test_that_route_is_never_granted_again_while_the_slab_is_on_it(run_log):
    _, records = run_log
    shift, _, permits, _ = split(records)
    rid = shifted_route(records)
    again = [p for p in permits if p["route"] == rid and p["granted"] and p["t"] > shift["t"]]
    assert again == [], again[0]["reason"] if again else ""


def test_every_grant_after_the_shift_is_a_fresh_look_and_avoids_the_slab(run_log):
    _, records = run_log
    shift, routes, permits, core = split(records)
    after = [p for p in permits if p["granted"] and p["t"] > shift["t"]]
    assert after, "no permit was granted after the shift: the rescue never moved on"
    for p in after:
        kinds = [e["kind"] for e in p["evidence"]]
        planned_after = routes[p["route"]]["t"] > shift["t"]
        assert "fresh_scan" in kinds or planned_after, f"{p['route']} granted by {kinds} with no fresh look"
        assert not (core & {tuple(c) for c in routes[p["route"]]["cells"]}), f"{p['route']} crosses the slab"
