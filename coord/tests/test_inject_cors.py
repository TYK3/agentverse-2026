"""LIVE-UI: the console may POST /inject on the hub from its dev origin, and nothing else opens up."""

import importlib.util
import json
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


@pytest.mark.parametrize("raw", [b"", b"not json", b'{"kind":'])
def test_live_sim_rejects_malformed_json_without_mutating_or_breaking_next_inject(
        clean_bus, restore_routes, raw):
    calls = []
    world = SimpleNamespace(trigger_aftershock=lambda: calls.append("aftershock") or True)
    assert _sim_inject().install(world, clean_bus)
    with TestClient(hub.app, raise_server_exceptions=False) as client:
        bad = client.post("/inject", content=raw,
                          headers={"Origin": CONSOLE, "content-type": "application/json"})
        assert bad.status_code == 400
        assert bad.headers["access-control-allow-origin"] == CONSOLE
        assert not calls and not clean_bus.history
        good = client.post("/inject", json={"kind": "aftershock"}, headers={"Origin": CONSOLE})
    assert good.status_code == 200 and good.json() == {"ok": True}
    assert calls == ["aftershock"]


@pytest.mark.parametrize("pos", [
    pytest.param([True, 0, 0], id="boolean"),
    pytest.param([float("nan"), 0, 0], id="nan"),
    pytest.param([0, float("inf"), 0], id="infinity"),
    pytest.param([0, 0, -float("inf")], id="negative-infinity"),
    pytest.param([1e308, 0, 0], id="overflowing-physics"),
    pytest.param([10**1000, 0, 0], id="huge-integer"),
    pytest.param([50.001, 0, 0], id="outside-scene-bound"),
])
def test_live_sim_rejects_unsafe_positions_before_world_call(clean_bus, restore_routes, pos):
    calls = []
    world = SimpleNamespace(add_block=lambda point: calls.append(point) or "spare1")
    assert _sim_inject().install(world, clean_bus)
    with TestClient(hub.app, raise_server_exceptions=False) as client:
        bad = client.post("/inject", content=json.dumps({"kind": "block_added", "pos": pos}),
                          headers={"content-type": "application/json"})
        assert bad.status_code == 400 and isinstance(bad.json()["error"], str)
        assert not calls
        valid = [0.6, 0.25, -1.8]
        good = client.post("/inject", json={"kind": "block_added", "pos": valid})
    assert good.status_code == 200 and calls == [valid]
    assert not clean_bus.history


@pytest.mark.parametrize("live", [False, True])
def test_deep_json_is_rejected_and_next_inject_still_works(clean_bus, restore_routes, live):
    calls = []
    if live:
        world = SimpleNamespace(trigger_aftershock=lambda: calls.append("aftershock") or True)
        assert _sim_inject().install(world, clean_bus)
    with TestClient(hub.app, raise_server_exceptions=False) as client:
        bad = client.post("/inject", content=b"[" * 100_000 + b"]" * 100_000,
                          headers={"Origin": CONSOLE, "content-type": "application/json"})
        assert bad.status_code == 400 and isinstance(bad.json()["error"], str)
        assert bad.headers["access-control-allow-origin"] == CONSOLE and not calls
        good = client.post("/inject", json={"kind": "aftershock"})
    assert good.status_code == (200 if live else 503)
    assert calls == (["aftershock"] if live else [])
    assert not clean_bus.history
