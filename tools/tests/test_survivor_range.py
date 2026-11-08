"""SURVIVOR-RANGE: on a live seed-0 B2 run, the Scout's closest approach to the B1
survivor stays within sensors.THERMAL_RANGE, and that approach is before any delivery.

A live ``tools/run_b2.py`` seed 0 with ``GEMINI_MODE=off`` finished in about 21 s,
under the 30 s cutoff, so this drives that runner rather than
``console/tests/fixtures/b2-seed0.jsonl``.
"""

import json
import math
import os
from pathlib import Path

import pytest

pytest.importorskip("mujoco")

from sim.levels import LEVEL_Z
from sim.scene import load
from sim.sensors import THERMAL_RANGE
from sim.world import casualties

NO_SURVIVOR = "no survivor on B1 in the seed-0 B2 run"


def b1_survivors(model, data):
    """Casualties on basement B1. Position comes from the loaded scene, not a literal."""
    found = []
    for name, geom, _voice in casualties(model):
        pos = data.geom_xpos[geom]
        z = float(pos[2])
        floor = min(LEVEL_Z, key=lambda level: abs(LEVEL_Z[level] - z))
        if floor == "B1":
            found.append({"id": name, "xy": (float(pos[0]), float(pos[1])), "z": z})
    return found


def is_delivery(record):
    """A supply placement. The B2 descent log has none of these records."""
    kind = record.get("kind")
    action = record.get("action")
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    if kind in {"delivery", "deliver", "place_supply"}:
        return True
    if action in {"place_supply", "deliver"} or data.get("action") in {"place_supply", "deliver"}:
        return True
    return record.get("topic") == "responder/action" and data.get("action") == "place_supply"


def closest_approach(poses, survivors):
    """Minimum xy distance from a B1 Scout pose to a B1 survivor, and when it happened."""
    best = None
    for survivor in survivors:
        sx, sy = survivor["xy"]
        for pose in poses:
            dist = math.hypot(pose["pos"][0] - sx, pose["pos"][1] - sy)
            if best is None or (dist, pose["t"]) < (best["dist"], best["t"]):
                best = {"id": survivor["id"], "dist": dist, "t": pose["t"], "pos": pose["pos"]}
    return best


@pytest.mark.slow
def test_scout_b1_approach_is_inside_thermal_range_before_delivery(tmp_path, request):
    os.environ["GEMINI_MODE"] = "off"
    from tools.run_b2 import run

    _verdict, path = run(seed=0, out_dir=tmp_path)
    records = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    model, data = load(tmp_path / "levels_with_slab.xml")
    survivors = b1_survivors(model, data)
    if not survivors:
        request.node.add_marker(pytest.mark.xfail(strict=True, reason=NO_SURVIVOR))
        pytest.fail(NO_SURVIVOR)

    poses = [r for r in records if r.get("kind") == "pose" and r.get("level") == "B1"]
    assert poses, "the seed-0 B2 run records no Scout pose on B1"
    closest = closest_approach(poses, survivors)
    # sensors.THERMAL_RANGE: the Scout treats a casualty as thermally visible only inside this
    # xy distance (sim/sensors.py, used by sim/world.py sensors_message).
    assert closest["dist"] <= THERMAL_RANGE, (
        f"closest approach to {closest['id']} is {closest['dist']:.3f} m at t={closest['t']} s, "
        f"beyond sensors.THERMAL_RANGE ({THERMAL_RANGE} m)"
    )
    delivery_t = min((r["t"] for r in records if is_delivery(r)), default=None)
    assert delivery_t is None or closest["t"] < delivery_t, (
        f"closest approach at t={closest['t']} s is not before the delivery at t={delivery_t} s"
    )
