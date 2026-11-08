"""HUB-HEALTH reports this hub lifecycle and actual sim task state without starting work."""

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from coord import hub


def quiet(monkeypatch, lanes=()):
    monkeypatch.setattr(hub, "bus", hub.Bus())
    monkeypatch.setattr(hub, "LANES", lanes)
    original = hub.importlib.import_module

    def imports(name):
        if name == "coord.gem":
            raise ModuleNotFoundError(name=name)
        return original(name)

    monkeypatch.setattr(hub.importlib, "import_module", imports)


def test_health_reports_uptime_and_absent_sim_without_publishing(monkeypatch):
    quiet(monkeypatch)
    with TestClient(hub.app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True and data["uptime_s"] >= 0
        assert data["sim"] == {"loaded": False, "running": False, "scene": None}
        assert not hub.bus.history and not hub.bus.latest


def test_health_tracks_sim_task_stopping_and_lifecycle_reset(monkeypatch):
    quiet(monkeypatch, ("sim",))
    original = hub.importlib.import_module
    world = SimpleNamespace(scene="levels")

    async def wait():
        await asyncio.Event().wait()

    async def start(_):
        world.task = asyncio.create_task(wait())
        return world

    def imports(name):
        return SimpleNamespace(start=start) if name == "sim" else original(name)

    async def stop():
        world.task.cancel()
        await asyncio.gather(world.task, return_exceptions=True)

    monkeypatch.setattr(hub.importlib, "import_module", imports)
    with TestClient(hub.app) as client:
        first = client.get("/health").json()
        assert first["sim"] == {"loaded": True, "running": True, "scene": "levels"}
        client.portal.call(stop)
        second = client.get("/health").json()
        assert second["sim"] == {"loaded": True, "running": False, "scene": "levels"}
        assert second["uptime_s"] >= first["uptime_s"]
    assert world.task.cancelled()
    monkeypatch.setattr(hub, "LANES", ())
    with TestClient(hub.app) as client:
        assert client.get("/health").json()["sim"] == {"loaded": False, "running": False, "scene": None}


def test_health_does_not_claim_a_live_hub_without_lifespan(monkeypatch):
    quiet(monkeypatch)
    # Also exercise cleanup after a normal startup/shutdown.
    with TestClient(hub.app) as client:
        assert client.get("/health").json()["ok"] is True
    response = TestClient(hub.app).get("/health")
    assert response.json() == {"ok": False, "uptime_s": 0.0,
                               "sim": {"loaded": False, "running": False, "scene": None}}
