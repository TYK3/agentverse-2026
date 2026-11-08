"""D1: complete depth-batch boundaries through the real validating hub/WebSocket."""

import json
from collections import deque
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from coord import gem, hub


@pytest.fixture
def browser_hub(monkeypatch):
    target = hub.Bus()
    monkeypatch.setattr(hub, "bus", target)
    monkeypatch.setattr(hub, "LANES", ())
    monkeypatch.setattr(gem, "MODE", "off")
    monkeypatch.setattr(gem, "_receipts", deque(maxlen=200))
    monkeypatch.setattr(gem, "_c", lambda: pytest.fail("D1 browser regression attempted an SDK call"))
    with TestClient(hub.app) as client:
        yield client, target


def sensors(points, t=12.5):
    return {"t": t, "pose": {"pos": [0, 0, -1], "yaw": 0}, "lidar": [1.0],
            "thermal": [[0.3]], "acoustic": {"bearing": 0, "level": 0.2},
            "camera": {"format": "jpeg", "b64": "private-development-image"},
            "points": points, "points_from": [0.1, 0.2, -0.8]}


def until(socket, topic):
    received = []
    for _ in range(8):
        message = socket.receive_json()
        assert message["topic"] != "sensors/scout"
        received.append(message)
        if message["topic"] == topic:
            return received
    pytest.fail(f"did not receive {topic}")


def test_full_2048_point_sensor_batch_reaches_browser_and_reconnect_once(browser_hub):
    client, target = browser_hub
    points = [[(i % 32) * 0.1 + 0.013, (i // 32) * 0.1 + 0.027, -1.0 if i < 1024 else -2.0]
              for i in range(2048)]
    with client.websocket_connect("/ws") as live:
        client.portal.call(target.publish, "sensors/scout", sensors(points))
        payload = until(live, "map/points")[-1]["data"]
        assert payload == {"t": 12.5, "res": 0.05, "points": points, "points_from": [0.1, 0.2, -0.8]}
        assert len(payload["points"]) == 2048
        assert "private-development-image" not in json.dumps(target.latest)
        assert all(item["topic"] not in ("map/points", "sensors/scout") for item in target.history)
        with client.websocket_connect("/ws") as reconnect:
            client.portal.call(target.publish, "status/link", {"online": False})
            replay = until(reconnect, "status/link")
            clouds = [item for item in replay if item["topic"] == "map/points"]
            assert len(clouds) == 1 and clouds[0]["data"] == payload


def test_oversized_source_is_rejected_without_replacing_cloud_then_empty_batch_clears(browser_hub):
    client, target = browser_hub
    with client.websocket_connect("/ws") as live:
        client.portal.call(target.publish, "sensors/scout", sensors([[0.013, 0.027, -1.0]]))
        until(live, "map/points")
        previous = deepcopy(target.latest)
        with pytest.raises(ValueError):
            client.portal.call(target.publish, "sensors/scout", sensors([[i, 0, -1] for i in range(2049)]))
        assert target.latest == previous
        client.portal.call(target.publish, "sensors/scout", sensors([], t=13.0))
        empty = until(live, "map/points")[-1]["data"]
        assert empty["points"] == [] and empty["t"] == 13.0
        assert target.latest["map/points"]["data"] == empty


def test_new_scene_prevents_old_basement_cloud_replay_to_late_browser(browser_hub):
    client, target = browser_hub
    with client.websocket_connect("/ws") as live:
        client.portal.call(target.publish, "sensors/scout", sensors([[0.013, 0.027, -2.0]]))
        until(live, "map/points")
        client.portal.call(target.publish, "scene/loaded", {"scene": "backup", "blocks": []})
        until(live, "scene/loaded")
        assert "map/points" not in target.latest
        with client.websocket_connect("/ws") as reconnect:
            client.portal.call(target.publish, "status/link", {"online": False})
            replay = until(reconnect, "status/link")
            assert any(item["topic"] == "scene/loaded" for item in replay)
            assert all(item["topic"] != "map/points" for item in replay)
