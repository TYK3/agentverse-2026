"""RELOOK-HAS-ORIGIN: every re-look in a real run log can be traced to what triggered it.

No runner on main logs re-looks (tools/run_b2.py and run_levels.py plan without move permits; the hub-level
tools/run_rescue.py is open PR #52). So this test makes a real log from the real parts on main, as on the bus:
MuJoCo LiDAR on the backup scene through perception's closed loop (perception/tests/closed_loop.py) into
the real planner.route.RoutePlanner and planner.permit.Permits. The Scout maps room 2, route r1 is
proposed and verified, then x1 lands across it. Only the Scout's own LiDAR and hazards reach the permits.
Every message they publish is logged (jsonl, read back). The Scout watches for 20 s, so the 8 s re-look
repeat also fires.

A re-look is a scout/goto whose reason starts "re-look". Its origin is the permit/route revocation that
started it: the route, the cause (a LiDAR hit inside the route, or a sensed hazard) and the cell.
  - pass: every re-look names a route that is revoked at that moment, and was revoked by a stated cause.
  - pass: every re-look goes to the cell that caused the revocation.
  - strict xfail, finding: the re-look's own reason does not say why. It is only "re-look to re-earn move
    permission on route r1"; the cause and cell are in the earlier permit/route message alone, so a
    console or log line showing the re-look cannot say what the Scout is checking. Closing it is a
    planner/permit.py change (_relook: add the evidence's detail to the reason).
Block poses are used only by the test world, to move x1, never by perception or the planner.
"""

import asyncio
import json
import re

import pytest

pytest.importorskip("mujoco")

SCOUT = (0.3, 0.2)             # where the Scout maps room 2 from, facing east
GOAL_XY = (0.95, 0.2)
X1_AT = (0.62, 0.2, 0.08)      # across the route (as in perception/tests/test_shift_reroute_e2e.py, #221)
WATCH_S = 20.0


class Bus:
    def __init__(self):
        self.published = []

    def subscribe(self, topic, callback):
        pass

    async def publish(self, topic, data):
        self.published.append((topic, data))


@pytest.fixture(scope="module")
def log(tmp_path_factory):
    import mujoco

    from perception.grid import cell_of
    from perception.tests.closed_loop import Loop
    from planner.permit import Permits
    from planner.route import RoutePlanner

    loop = Loop(start=SCOUT, depth=False)
    permits = Permits()
    records = []

    def out(t, pairs):
        records.extend({"t": round(t, 2), "topic": topic, "data": data} for topic, data in pairs)

    hazards_sensors = loop.hazards.on_sensors

    def tee(data):                                     # every Scout frame also reaches the permits
        hazards_sensors(data)
        out(data["t"], permits.on_sensors(data, data["t"]))
        if round(data["t"] * 10) % 10 == 0:            # map/hazards at 1 Hz, as perception publishes it
            out(data["t"], permits.on_hazards(loop.hazards.message() or [], data["t"]))

    loop.hazards.on_sensors = tee
    loop.watch(*SCOUT, 0.0, 30)

    planner = RoutePlanner(Bus())
    planner.update_map(loop.grid.snapshot(loop.t))
    planner.update_hazards(loop.hazards.message())

    def ground(xy):
        i, j, _ = cell_of((xy[0], xy[1], 0.0))
        return (i, j, 0)

    route = asyncio.run(planner.propose(ground(SCOUT), ground(GOAL_XY)))
    assert route["status"] == "ok", route
    route = {**route, "id": "r1"}
    out(loop.t, [("route/proposed", route)] + permits.on_route_proposed(route))
    out(loop.t, permits.on_route_verified({"id": "r1", "ok": True}, loop.t))

    adr = loop.m.joint(loop.m.body("x1").jntadr[0]).qposadr[0]
    loop.d.qpos[adr:adr + 7] = [*X1_AT, 1, 0, 0, 0]
    mujoco.mj_forward(loop.m, loop.d)
    loop.hazards.on_change({"kind": "inject", "t": loop.t, "moved_blocks": ["x1"]}, loop.t)
    records.append({"t": loop.t, "topic": "world/change", "data": {"kind": "inject"}})
    loop.watch(*SCOUT, 0.0, int(WATCH_S * 10))

    path = tmp_path_factory.mktemp("relook") / "relook-origin.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def relooks(log):
    return [r for r in log if r["topic"] == "scout/goto" and r["data"]["reason"].startswith("re-look")]


def revocations(log, route):
    return [r for r in log if r["topic"] == "permit/route" and r["data"]["route"] == route
            and not r["data"]["granted"] and r["data"]["reason"].startswith("revoked")]


def route_of(goto):
    return re.search(r"on route (r\d+)", goto["data"]["reason"]).group(1)


def origin(log, goto):
    """The revocation that started this re-look: the last one for its route at or before it, not re-granted."""
    route = route_of(goto)
    before = [r for r in log if r["topic"] == "permit/route" and r["data"]["route"] == route and r["t"] <= goto["t"]]
    last = before[-1] if before else None
    return last if last and not last["data"]["granted"] and last["data"]["reason"].startswith("revoked") else None


def test_the_shift_revokes_r1_and_the_scout_is_sent_to_re_look(log):
    assert revocations(log, "r1"), "x1 on the route never revoked r1"
    looks = relooks(log)
    assert len(looks) >= 2, f"{len(looks)} re-looks: the 8 s repeat should also fire in {WATCH_S} s"


def test_every_re_look_traces_to_a_stated_revocation(log):
    for goto in relooks(log):
        o = origin(log, goto)
        assert o is not None, f"re-look at {goto['t']} s ({goto['data']['reason']}) has no live revocation"
        cause = o["data"]["evidence"][-1]
        assert cause["kind"] in ("shift", "hazard") and cause["detail"], o


def test_every_re_look_goes_to_the_cell_that_caused_it(log):
    for goto in relooks(log):
        detail = origin(log, goto)["data"]["evidence"][-1]["detail"]
        target = goto["data"]["target"]
        cell = [int(target[0] // 0.05), int(target[1] // 0.05)]
        assert str(cell) in detail or "hazard" in detail, f"re-look to {cell}, origin: {detail}"


@pytest.mark.xfail(strict=True, reason="planner/permit.py: a re-look's reason names its route but not its cause")
def test_a_re_look_says_why_in_its_own_reason(log):
    for goto in relooks(log):
        cause = origin(log, goto)["data"]["evidence"][-1]["detail"]
        assert cause in goto["data"]["reason"], f"{goto['data']['reason']!r} does not say {cause!r}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
