"""Contract fixtures and transport regressions, with no network/model calls."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from coord import hub
from coord.messages import TOPICS, validate_payload

FIXTURES = Path(__file__).parents[1] / "fixtures"
EXAMPLES = [json.loads(path.read_text()) for path in sorted(FIXTURES.glob("*.json"))]


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


def test_one_fixture_per_topic():
    assert {item["topic"] for item in EXAMPLES} == set(TOPICS)
    assert len(EXAMPLES) == len(TOPICS)


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda item: item["topic"])
def test_checked_fixture_to_websocket(clean_bus, example):
    TOPICS[example["topic"]].model_validate(example["data"])
    with TestClient(hub.app) as client, client.websocket_connect("/ws") as websocket:
        client.portal.call(hub.publish_checked, example["topic"], example["data"])
        if example["topic"] == "sensors/scout":
            assert not clean_bus.history
            client.portal.call(hub.publish_checked, "status/link", {"online": True})
            assert websocket.receive_json() == {"topic": "status/link", "data": {"online": True}}
        else:
            assert websocket.receive_json() == example


def test_local_subscribers_and_recursive_publish(clean_bus):
    seen = []
    clean_bus.subscribe("status/link", lambda data: seen.append(data))

    async def callback(data):
        await clean_bus.publish("operator/command", {"text": "stop", "source": "typed"})

    clean_bus.subscribe("status/link", callback)
    asyncio.run(clean_bus.publish("status/link", {"online": False}))
    assert seen == [{"online": False}]
    assert [m["topic"] for m in clean_bus.history] == ["status/link", "operator/command"]


def test_sensors_only_go_to_local_subscribers(clean_bus):
    example = next(item for item in EXAMPLES if item["topic"] == "sensors/scout")
    seen = []
    clean_bus.subscribe("sensors/scout", seen.append)
    asyncio.run(clean_bus.publish(example["topic"], example["data"]))
    assert seen == [example["data"]]
    assert not clean_bus.history


def test_scout_camera_motion_and_recording_shapes():
    example = next(item for item in EXAMPLES if item["topic"] == "sensors/scout")
    data = dict(example["data"])
    data["motion"] = {"state": "moving", "target": [1, 2]}
    data["camera"] = {"format": "jpeg", "b64": "development-example"}
    assert validate_payload("sensors/scout", data) == data
    data.pop("camera")
    data.pop("t")
    assert validate_payload("sensors/scout", data) == data


def test_scout_depth_points_are_optional_xyz_and_capped():
    example = next(item for item in EXAMPLES if item["topic"] == "sensors/scout")
    data = dict(example["data"], points=[[0.1, 0.2, 0.3], [1, 2, 0.05]])
    assert validate_payload("sensors/scout", data) == data
    for bad in ([[0.1, 0.2]], [[0, 0, 0]] * 2049):
        with pytest.raises(ValueError):
            validate_payload("sensors/scout", dict(data, points=bad))


def test_broken_subscriber_and_disconnected_client(clean_bus):
    seen = []

    def broken(data):
        raise RuntimeError("broken subscriber")

    async def failed_send(message):
        raise RuntimeError("disconnected")

    class Client:
        send_text = staticmethod(failed_send)

    client = Client()
    clean_bus.clients.add(client)
    clean_bus.subscribe("status/link", broken)
    clean_bus.subscribe("status/link", seen.append)
    asyncio.run(clean_bus.publish("status/link", {"online": True}))
    assert client not in clean_bus.clients
    assert seen == [{"online": True}]


def test_bounded_history_and_late_join(clean_bus):
    async def seed():
        for i in range(205):
            await clean_bus.publish("operator/command", {"text": str(i), "source": "typed"})

    asyncio.run(seed())
    assert len(clean_bus.history) == 200
    with TestClient(hub.app) as client, client.websocket_connect("/ws") as websocket:
        assert [websocket.receive_json()["data"]["text"] for _ in range(200)] == [
            str(i) for i in range(5, 205)
        ]
        websocket.send_json({"topic": "gate/answer", "data": {
            "id": "g1", "approved": True, "by": "operator"
        }})
        assert websocket.receive_json()["topic"] == "gate/answer"
    assert not clean_bus.clients


@pytest.mark.parametrize("raw", [
    "not json", "[]", "{}", '{"topic":"status/link","data":{"online":"false"}}',
    '{"topic":"world/change","data":{"kind":"block_added","t":1,"moved_blocks":["x1"]}}',
    '{"topic":"gate/answer","data":{"id":"g1","approved":"false","by":"operator"}}',
    '{"topic":"operator/command","data":{"text":"stop","source":"typed","extra":1}}',
    '{"topic":"operator/command","data":{"text":"stop","source":"typed"},"extra":1}',
])
def test_invalid_browser_input_closes_before_dispatch(clean_bus, raw):
    with TestClient(hub.app) as client, client.websocket_connect("/ws") as websocket:
        websocket.send_text(raw)
        with pytest.raises(WebSocketDisconnect) as exc:
            websocket.receive_json()
        assert exc.value.code == 1008
    assert not clean_bus.history
    assert not clean_bus.clients


def test_browser_command_reaches_subscriber(clean_bus):
    seen = []
    with TestClient(hub.app) as client, client.websocket_connect("/ws") as websocket:
        clean_bus.subscribe("operator/command", seen.append)
        message = {"topic": "operator/command", "data": {"text": "stop", "source": "typed"}}
        websocket.send_json(message)
        assert websocket.receive_json() == message
    assert seen == [message["data"]]


def test_browser_offline_toggle_reaches_subscriber(clean_bus):
    seen = []
    with TestClient(hub.app) as client, client.websocket_connect("/ws") as websocket:
        clean_bus.subscribe("status/link", seen.append)
        message = {"topic": "status/link", "data": {"online": False}}
        websocket.send_json(message)
        assert websocket.receive_json() == message
    assert seen == [{"online": False}]


def test_sim_injected_block_change_reaches_subscriber_and_browser(clean_bus):
    seen = []
    with TestClient(hub.app) as client, client.websocket_connect("/ws") as websocket:
        clean_bus.subscribe("world/change", seen.append)
        data = {"kind": "block_added", "t": 1.0, "moved_blocks": ["x1"]}
        client.portal.call(hub.publish_checked, "world/change", data)
        assert websocket.receive_json() == {"topic": "world/change", "data": data}
    assert seen == [data]


@pytest.mark.parametrize("topic,data", [
    ("missing", {}), ("status/link", {"online": "false"}),
    ("gate/decision", {"id": "d1", "outcome": "act", "confidence": 2, "reason": "test"}),
    ("map/cells", {"t": 0, "res": 0.1, "cells": [
        {"cell": [1, 2], "state": "seen", "occupied": False}]}),
    ("status/budget", {"device": "test", "mem_mb": float("nan"), "model": "test",
                       "ms_per_step": 0, "limit": {}}),
])
def test_validation_precedes_dispatch(clean_bus, topic, data):
    seen = []
    clean_bus.subscribe(topic, seen.append)
    with pytest.raises(ValueError):
        asyncio.run(clean_bus.publish(topic, data))
    assert not seen
    assert not clean_bus.history


def test_array_payloads_and_local_provenance():
    assert validate_payload("map/casualties", []) == []
    assert validate_payload("map/hazards", []) == []
    example = next(item for item in EXAMPLES if item["topic"] == "route/proposed")
    assert validate_payload(example["topic"], example["data"])["model"] == "local-astar"


def test_startup_lanes_status_and_cleanup(clean_bus, monkeypatch):
    calls = []
    tasks = []

    async def start(target):
        calls.append(target)
        task = asyncio.create_task(asyncio.sleep(1000))
        tasks.append(task)
        return SimpleNamespace(task=task)

    def imports(name):
        if name == "missing":
            raise ModuleNotFoundError(name=name)
        if name == "empty":
            return SimpleNamespace()
        if name == "coord.gem":
            return SimpleNamespace(status=lambda: {"mode": "off", "calls_last_hour": 0,
                                                    "stand_ins": []})
        return SimpleNamespace(start=start)

    monkeypatch.setattr(hub, "LANES", ("missing", "empty", "ready"))
    monkeypatch.setattr(hub.importlib, "import_module", imports)
    with TestClient(hub.app) as client, client.websocket_connect("/ws") as websocket:
        assert websocket.receive_json()["topic"] == "status/gemini"
    assert calls == [clean_bus]
    assert all(task.cancelled() for task in tasks)


def test_docs(clean_bus):
    with TestClient(hub.app) as client:
        assert client.get("/docs").status_code == 200


def test_scene_loaded_accepts_the_tower_scene():
    """sim/scenes/tower.xml (ref Y1) publishes scene/loaded with scene "tower"."""
    from coord.messages import validate_payload

    payload = {"scene": "tower", "blocks": [{"id": "b1", "label": "slab", "pos": [0.0, 0.0, 1.05], "size": [1.0, 1.0, 0.05]}]}
    assert validate_payload("scene/loaded", payload)["scene"] == "tower"


def test_hazard_exclusion_and_points_from_are_optional():
    hazard = {"cell": [1, 2, 0], "status": "at_risk", "why": "slab moved", "estimate": True}
    assert validate_payload("map/hazards", [hazard]) == [hazard]
    assert validate_payload("map/hazards", [dict(hazard, exclusion=True)]) == [dict(hazard, exclusion=True)]
    with pytest.raises(ValueError):
        validate_payload("map/hazards", [dict(hazard, exclusion="yes")])
    example = next(item for item in EXAMPLES if item["topic"] == "sensors/scout")
    data = dict(example["data"], points=[[0.1, 0.2, 0.3]], points_from=[0.0, 0.0, 0.18])
    assert validate_payload("sensors/scout", data) == data


def test_scene_loaded_accepts_the_building_scene():
    """sim/scenes/building.xml (ref Y1b) publishes scene/loaded with scene "building"."""
    from coord.messages import validate_payload

    payload = {"scene": "building", "blocks": [{"id": "b1", "label": "column", "pos": [0.0, 0.0, 1.4], "size": [0.15, 0.15, 1.4]}]}
    assert validate_payload("scene/loaded", payload)["scene"] == "building"


def test_scene_loaded_accepts_the_tower_annex_scene():
    """sim/scenes/tower_annex.xml publishes scene/loaded with scene "tower_annex" (TOWER-ANNEX-SCENE)."""
    from coord.messages import validate_payload

    payload = {"scene": "tower_annex", "blocks": [{"id": "b1", "label": "wall", "pos": [0.0, 0.0, 0.5], "size": [0.1, 1.0, 0.5]}]}
    assert validate_payload("scene/loaded", payload)["scene"] == "tower_annex"
