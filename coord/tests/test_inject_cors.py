"""LIVE-UI: the console may POST /inject on the hub from its dev origin, and nothing else opens up."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from coord import hub

INJECT_PY = Path(__file__).parents[2] / "sim" / "inject.py"
CONSOLE = "http://localhost:5173"


@pytest.fixture
def clean_bus(monkeypatch):
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


@pytest.fixture
def restore_routes():
    routes = list(hub.app.router.routes)
    yield
    hub.app.router.routes[:] = routes


def preflight(client, origin, path="/inject", method="POST"):
    return client.options(path, headers={
        "Origin": origin,
        "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": "content-type",
    })


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_console_origins_may_preflight_inject(clean_bus, origin):
    with TestClient(hub.app) as client:
        response = preflight(client, origin)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", ["http://evil.example", "http://localhost:3000", "null"])
def test_other_origins_are_refused(clean_bus, origin):
    with TestClient(hub.app) as client:
        response = preflight(client, origin)
        posted = client.post("/inject", json={"kind": "aftershock"}, headers={"Origin": origin})
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-origin" not in posted.headers


def test_only_get_and_post_are_allowed_cross_origin(clean_bus):
    with TestClient(hub.app) as client:
        response = preflight(client, CONSOLE, method="DELETE")
    assert response.status_code == 400


def test_extra_origins_from_env_but_never_wildcard():
    origins = hub.cors_origins({"HUB_CORS_ORIGINS": " http://192.168.1.5:5173 ,*,, "})
    assert origins == hub.CONSOLE_ORIGINS + ["http://192.168.1.5:5173"]
    assert hub.cors_origins({}) == hub.CONSOLE_ORIGINS


def test_inject_without_a_sim_is_503_and_publishes_nothing(clean_bus):
    seen = []
    clean_bus.subscribe("world/change", seen.append)
    with TestClient(hub.app) as client:
        response = client.post("/inject", json={"kind": "aftershock"}, headers={"Origin": CONSOLE})
    assert response.status_code == 503
    assert response.json() == {"error": "no live sim on this hub"}
    assert response.headers["access-control-allow-origin"] == CONSOLE
    assert not seen and not clean_bus.history


@pytest.mark.parametrize("body", [
    {"kind": "map/cells"}, {"topic": "world/change", "data": {}}, {}, [], "aftershock",
])
def test_inject_rejects_other_kinds_and_topics(clean_bus, body):
    with TestClient(hub.app) as client:
        response = client.post("/inject", json=body, headers={"Origin": CONSOLE})
    assert response.status_code == 400
    assert not clean_bus.history


def test_inject_rejects_non_json(clean_bus):
    with TestClient(hub.app) as client:
        response = client.post("/inject", content=b"not json",
                               headers={"Origin": CONSOLE, "content-type": "application/json"})
    assert response.status_code == 400


def _sim_inject():
    """Load sim/inject.py on its own (it only imports sys), so coord CI needs no MuJoCo."""
    spec = importlib.util.spec_from_file_location("sim_inject_for_hub_test", INJECT_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_sim_route_replaces_the_stand_in_and_is_reachable_from_the_console(
        clean_bus, restore_routes):
    calls = []
    world = SimpleNamespace(
        trigger_aftershock=lambda: calls.append("aftershock") or True,
        add_block=lambda pos: calls.append(("block_added", pos)) or "spare1",
    )
    assert _sim_inject().install(world, clean_bus)
    assert [getattr(r, "path", None) for r in hub.app.router.routes].count("/inject") == 1
    with TestClient(hub.app) as client:
        shake = client.post("/inject", json={"kind": "aftershock"}, headers={"Origin": CONSOLE})
        block = client.post("/inject", json={"kind": "block_added", "pos": [0.6, 0.25, 0.1]},
                            headers={"Origin": CONSOLE})
        bad = client.post("/inject", json={"kind": "block_added"}, headers={"Origin": CONSOLE})
    assert shake.status_code == 200 and shake.headers["access-control-allow-origin"] == CONSOLE
    assert block.json() == {"ok": True, "block": "spare1"}
    assert bad.status_code == 400
    assert calls == ["aftershock", ("block_added", [0.6, 0.25, 0.1])]


def test_console_hold_and_approve_reach_the_planner_as_gate_answer(clean_bus):
    """LIVE-UI-2: the console's Approve / Reject (hold) use the contract's gate/answer write."""
    seen = []
    with TestClient(hub.app) as client, client.websocket_connect("/ws") as websocket:
        clean_bus.subscribe("gate/answer", seen.append)
        for gate, approved in (("g-a", True), ("g-h", False)):
            websocket.send_json({"topic": "gate/answer",
                                 "data": {"id": gate, "approved": approved, "by": "operator"}})
            assert websocket.receive_json()["data"]["approved"] is approved
    assert [(a["id"], a["approved"]) for a in seen] == [("g-a", True), ("g-h", False)]


def test_slab_shift_block_added_without_a_sim_is_503(clean_bus):
    with TestClient(hub.app) as client:
        response = client.post("/inject", json={"kind": "block_added", "pos": [0.575, 0.025, 0.3]},
                               headers={"Origin": CONSOLE})
    assert response.status_code == 503 and not clean_bus.history
