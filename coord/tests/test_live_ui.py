"""LIVE-UI-3: browser -> hub inject and gate/answer path, without a MuJoCo sim.

Playwright drives the console at http://127.0.0.1:5173, so the browser Origin is that URL.
Simulate Re-Plan POSTs /inject {kind: aftershock}; Trigger Slab Shift POSTs
{kind: block_added, pos} (the 0.5 m-ahead drop from live-controls.ts); Approve / hold send
gate/answer {id, approved, by: "operator"} on /ws.
"""

from fastapi.testclient import TestClient

from coord import hub

BROWSER = "http://127.0.0.1:5173"


def _quiet_hub(monkeypatch):
    target = hub.Bus()
    monkeypatch.setattr(hub, "bus", target)
    monkeypatch.setattr(hub, "LANES", ())
    original = hub.importlib.import_module

    def imports(name):
        if name == "coord.gem":
            raise ModuleNotFoundError(name=name)
        return original(name)

    monkeypatch.setattr(hub.importlib, "import_module", imports)
    return target


def test_browser_origin_replan_and_slab_shift_without_a_sim_are_503(monkeypatch):
    bus = _quiet_hub(monkeypatch)
    seen = []
    bus.subscribe("world/change", seen.append)
    headers = {"Origin": BROWSER}
    with TestClient(hub.app) as client:
        aftershock = client.post("/inject", json={"kind": "aftershock"}, headers=headers)
        slab = client.post("/inject", json={"kind": "block_added", "pos": [0.575, 0.025, 0.3]},
                           headers=headers)
    for response in (aftershock, slab):
        assert response.status_code == 503
        assert response.json() == {"error": "no live sim on this hub"}
        assert response.headers["access-control-allow-origin"] == BROWSER
    assert not seen and not bus.history


def test_browser_approve_and_hold_reach_lane_subscribers(monkeypatch):
    bus = _quiet_hub(monkeypatch)
    seen = []
    with TestClient(hub.app) as client, client.websocket_connect("/ws") as websocket:
        bus.subscribe("gate/answer", seen.append)
        websocket.send_json({"topic": "gate/answer",
                             "data": {"id": "g-a", "approved": True, "by": "operator"}})
        websocket.send_json({"topic": "gate/answer",
                             "data": {"id": "g-h", "approved": False, "by": "operator"}})
        assert websocket.receive_json()["data"] == {"id": "g-a", "approved": True, "by": "operator"}
        assert websocket.receive_json()["data"] == {"id": "g-h", "approved": False, "by": "operator"}
    assert seen == [
        {"id": "g-a", "approved": True, "by": "operator"},
        {"id": "g-h", "approved": False, "by": "operator"},
    ]
