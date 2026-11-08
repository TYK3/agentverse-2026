"""D1 exposes bounded measured xyz batches, not raw sensor frames."""

import pytest

from coord.messages import validate_payload


def test_point_contract_preserves_scene_height_and_optional_origin():
    cloud = {"t": 0.5, "res": 0.05, "points": [[0.1, 0.2, -1.0]]}
    assert validate_payload("map/points", cloud) == cloud
    origin = {**cloud, "points_from": [0.0, 0.0, 0.18]}
    assert validate_payload("map/points", origin) == origin
    assert validate_payload("map/points", {**cloud, "points": []})["points"] == []


@pytest.mark.parametrize("changes", [
    {"points": [[0, 0, 0]] * 2049}, {"points": [[1, 2]]},
    {"points": [[0, 0, float("nan")]]}, {"res": 0}, {"t": -1},
    {"camera": {"b64": "private"}}, {"thermal": [[0.1]]},
])
def test_point_contract_rejects_unbounded_or_raw_sensor_data(changes):
    with pytest.raises(ValueError):
        validate_payload("map/points", {"t": 0, "res": 0.05, "points": [], **changes})
