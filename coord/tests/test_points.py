"""D1: measured coordinates, burst coalescing, bounded replay and private-frame isolation."""

import asyncio
import json
from collections import deque

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from coord import gem, hub
from coord.points import PERIOD, PointCloudPublisher


def test_projection_keeps_measured_xyz_and_origin_without_raw_fields():
    target = hub.Bus()
    bridge = PointCloudPublisher(target)
    measured = [[0.011, 0.021, -1.019], [0.012, 0.022, -1.018], [0.07, 0.02, 0.03]]
    bridge.on_sensors({"t": 4, "points": measured, "points_from": [0, 0, -0.8], "camera": "private-image"})
    measured[0][0] = 999
    asyncio.run(bridge.flush())
    assert target.latest["map/points"]["data"] == {
        "t": 4, "res": 0.05, "points": [[0.011, 0.021, -1.019], [0.07, 0.02, 0.03]], "points_from": [0, 0, -0.8]}
    assert not target.history and "private-image" not in json.dumps(target.latest)


def test_bursts_coalesce_missing_depth_is_ignored_and_empty_depth_clears():
    target = hub.Bus()
    bridge = PointCloudPublisher(target)
    for tick in range(100):
        bridge.on_sensors({"t": tick, "points": [[tick, 0, 0]]})
    bridge.on_sensors({"t": 101})
    bridge.on_sensors({"t": 102, "points": None})
    asyncio.run(bridge.flush())
    assert target.latest["map/points"]["data"]["t"] == 99 and bridge.pending is None
    bridge.on_sensors({"t": 103, "points": []})
    asyncio.run(bridge.flush())
    assert target.latest["map/points"]["data"]["points"] == []


def test_pending_and_reconnect_storage_are_bounded():
    target = hub.Bus()
    bridge = PointCloudPublisher(target)
    bridge.on_sensors({"t": 0, "points": [[i, 0, 0] for i in range(3000)]})
    assert len(bridge.pending["points"]) == 2048
    asyncio.run(bridge.flush())
    assert len(target.latest) == 1 and len(target.latest["map/points"]["data"]["points"]) == 2048


def test_clouds_do_not_evict_events_and_reconnect_gets_only_latest_cloud():
    target = hub.Bus()

    async def traffic():
        for tick in range(205):
            await target.publish("status/link", {"online": bool(tick % 2)})
            await target.publish("map/points", {"t": tick, "res": 0.05, "points": [[tick, 0, 0]]})

    asyncio.run(traffic())
    assert len(target.history) == 200 and all(item["topic"] == "status/link" for item in target.history)

    class Browser:
        def __init__(self):
            self.received = []

        async def send_text(self, text):
            self.received.append(json.loads(text))

    browser = Browser()
    asyncio.run(target.connect(browser))
    assert len(browser.received) == 201
    assert browser.received[-1]["topic"] == "map/points" and browser.received[-1]["data"]["t"] == 204


def test_scene_change_clears_pending_and_reconnect_clouds():
    target = hub.Bus()
    bridge = PointCloudPublisher(target)
    bridge.on_sensors({"t": 1, "points": [[1, 2, 3]]})
    asyncio.run(bridge.flush())
    bridge.on_sensors({"t": 2, "points": [[4, 5, 6]]})
    asyncio.run(target.publish("scene/loaded", {"scene": "backup", "blocks": []}))
    assert bridge.pending is None and "map/points" not in target.latest


def test_half_second_cadence_never_republishes_a_stale_frame(monkeypatch):
    target = hub.Bus()
    bridge = PointCloudPublisher(target)
    bridge.on_sensors({"t": 1, "points": [[1, 2, 3]]})
    messages, sleeps = [], []
    target.subscribe("map/points", messages.append)

    async def advance(delay):
        sleeps.append(delay)
        if len(sleeps) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", advance)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(bridge.run())
    assert sleeps == [PERIOD] * 3 and PERIOD == 0.5 and len(messages) == 1


def test_hub_projects_local_sensors_and_rejects_browser_cloud_writes(monkeypatch):
    target = hub.Bus()
    monkeypatch.setattr(hub, "bus", target)
    monkeypatch.setattr(hub, "LANES", ())
    monkeypatch.setattr(gem, "_receipts", deque(maxlen=200))
    fixture = {"pose": {"pos": [0, 0, 0], "yaw": 0}, "lidar": [], "thermal": [],
               "acoustic": {"bearing": 0, "level": 0}, "points": [[0.2, 0.3, -1]], "t": 0.5}
    with TestClient(hub.app) as client, client.websocket_connect("/ws") as socket:
        client.portal.call(target.publish, "sensors/scout", fixture)
        for _ in range(10):
            message = socket.receive_json()
            assert message["topic"] != "sensors/scout"
            if message["topic"] == "map/points":
                break
        else:
            pytest.fail("no point cloud received")
        assert message["data"]["points"] == [[0.2, 0.3, -1]]
        assert all(item["topic"] not in ("sensors/scout", "map/points") for item in target.history)
        socket.send_json({"topic": "map/points", "data": message["data"]})
        with pytest.raises(WebSocketDisconnect) as close:
            socket.receive_json()
        assert close.value.code == 1008
