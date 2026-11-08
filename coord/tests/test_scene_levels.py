"""SCENE-B2: the levels scene is distinct from a floor name and preserves scene-frame heights."""

from collections import deque

import pytest
from fastapi.testclient import TestClient

from coord import gem, hub
from coord.messages import validate_payload


def levels_scene():
    return {"scene": "levels", "blocks": [
        {"id": f"b{index}", "label": "slab", "pos": [0.0, 0.0, z], "size": [0.4, 0.3, 0.05]}
        for index, z in enumerate((0.6, 0.0, -0.6, -1.2), start=1)]}


def test_levels_scene_preserves_l1_ground_b1_b2_heights():
    payload = levels_scene()
    assert validate_payload("scene/loaded", payload) == payload


@pytest.mark.parametrize("floor_name", ["B1", "B2", "unknown"])
def test_floor_labels_are_not_accepted_as_unregistered_scene_names(floor_name):
    with pytest.raises(ValueError):
        validate_payload("scene/loaded", {**levels_scene(), "scene": floor_name})


def test_levels_basement_blocks_reach_browser_without_height_flattening(monkeypatch):
    target = hub.Bus()
    monkeypatch.setattr(hub, "bus", target)
    monkeypatch.setattr(hub, "LANES", ())
    monkeypatch.setattr(gem, "MODE", "off")
    monkeypatch.setattr(gem, "_receipts", deque(maxlen=200))
    monkeypatch.setattr(gem, "_c", lambda: pytest.fail("scene transport attempted a model call"))
    with TestClient(hub.app) as client, client.websocket_connect("/ws") as socket:
        client.portal.call(target.publish, "scene/loaded", levels_scene())
        for _ in range(4):
            message = socket.receive_json()
            if message["topic"] == "scene/loaded":
                break
        else:
            pytest.fail("levels scene never reached browser")
        assert message["data"] == levels_scene()
