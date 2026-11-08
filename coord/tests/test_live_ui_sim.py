"""LIVE-UI-3: the console's live controls against the real sim lane on the hub (needs MuJoCo).

Skipped where MuJoCo is not installed (the coord CI job); runs locally and in the full-test job.
The console posts from its dev origin exactly what console/src/map.ts (Simulate Re-Plan) and
console/src/live-controls.ts (Trigger Slab Shift) send; approve / hold is gate/answer on /ws.
"""

import time

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("mujoco")

from coord import hub

CONSOLE = {"Origin": "http://localhost:5173"}


@pytest.fixture
def live_sim(monkeypatch):
    monkeypatch.delenv("SIM_SCENE", raising=False)   # the backup scene, as the demo uses
    monkeypatch.setattr(hub, "bus", hub.Bus())
    monkeypatch.setattr(hub, "LANES", ("sim",))
    original = hub.importlib.import_module

    def imports(name):
        if name == "coord.gem":
            raise ModuleNotFoundError(name=name)
        return original(name)

    monkeypatch.setattr(hub.importlib, "import_module", imports)
    routes = list(hub.app.router.routes)
    with TestClient(hub.app) as client, client.websocket_connect("/ws") as websocket:
        yield client, websocket
    hub.app.router.routes[:] = routes


def next_world_change(websocket, within=30.0):
    end = time.monotonic() + within
    while time.monotonic() < end:
        message = websocket.receive_json()
        if message["topic"] == "world/change":
            return message["data"]
    raise AssertionError("no world/change")


def test_simulate_replan_triggers_a_real_aftershock(live_sim):
    client, websocket = live_sim
    response = client.post("/inject", json={"kind": "aftershock"}, headers=CONSOLE)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == CONSOLE["Origin"]
    change = next_world_change(websocket)
    assert change["kind"] == "aftershock"
    assert change["moved_blocks"], "a real aftershock moves blocks the sim measured"
    again = client.post("/inject", json={"kind": "aftershock"}, headers=CONSOLE)
    assert again.status_code in (200, 409)   # 409 only while one is still shaking


def test_slab_shift_drops_the_spare_block_once(live_sim):
    client, websocket = live_sim
    body = {"kind": "block_added", "pos": [-0.9, 0.25, 0.3]}
    first = client.post("/inject", json=body, headers=CONSOLE)
    assert first.status_code == 200
    block = first.json()["block"]
    change = next_world_change(websocket)
    assert change["kind"] == "block_added"
    assert change["moved_blocks"] == [block]
    second = client.post("/inject", json=body, headers=CONSOLE)
    assert second.status_code == 409
    assert second.json() == {"error": "no spare block left"}


def test_hold_from_the_console_reaches_lane_subscribers(live_sim):
    _, websocket = live_sim
    seen = []
    hub.bus.subscribe("gate/answer", seen.append)
    websocket.send_json({"topic": "gate/answer", "data": {"id": "g1", "approved": False, "by": "operator"}})
    end = time.monotonic() + 5
    while not seen and time.monotonic() < end:
        time.sleep(0.05)
    assert seen == [{"id": "g1", "approved": False, "by": "operator"}]
