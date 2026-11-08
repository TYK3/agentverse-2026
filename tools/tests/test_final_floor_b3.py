"""FINAL-FLOOR-B3: a real `run_b2 --floor B3` log ends on B3, with the robot there.

"Ends on B3" means both:
  - the last "level" record (each floor reached) is B3, and
  - the last measured "pose" is on B3: its floor is derived from pos z using the
    sim's floor heights (sim.levels.LEVEL_Z, plus RIDE, the body height above the
    floor), not from the pose's own label, and that label must agree.
The summary's final_level / final_pos must agree with the same derivation.
"""

import json

import pytest

from sim.levels import LEVEL_Z, RIDE

TOL = 0.022  # metres; same floor-label tolerance as test_basement_order


def floor_of_z(z):
    """Floor whose height (plus RIDE) matches z within TOL, or None (e.g. on a ramp)."""
    hits = [name for name, fz in LEVEL_Z.items() if abs(z - RIDE - fz) < TOL]
    return hits[0] if len(hits) == 1 else None


def check_ends_on(rows, floor):
    levels = [r for r in rows if r.get("kind") == "level"]
    assert levels, "no level records"
    assert levels[-1]["level"] == floor, f"last level record is {levels[-1]['level']}"
    poses = [r for r in rows if r.get("kind") == "pose"]
    assert poses, "no pose records"
    last = poses[-1]
    derived = floor_of_z(last["pos"][2])
    assert derived == floor, f"last pose z {last['pos'][2]} is on {derived}, not {floor}"
    assert last.get("level") == floor, f"last pose labelled {last.get('level')}"
    summary = next((r for r in reversed(rows) if r.get("kind") == "summary"), None)
    if summary is not None:
        assert summary.get("final_level") == floor, f"summary final_level {summary.get('final_level')}"
        assert floor_of_z(summary["final_pos"][2]) == floor, "summary final_pos not on floor"


def synthetic(end="B3", z_floor=None):
    rows = [{"t": 0, "kind": "level", "level": "L1"}]
    for i, name in enumerate(["ground", "B1", "B2", "B3"][: ["ground", "B1", "B2", "B3"].index(end) + 1]):
        rows.append({"t": i + 1, "kind": "level", "level": name})
    z = LEVEL_Z[z_floor or end] + RIDE
    rows.append({"t": 9, "kind": "pose", "pos": [1.0, 1.0, z], "level": end})
    rows.append({"t": 9.5, "kind": "summary", "floor": "B3", "final_level": end, "final_pos": [1.0, 1.0, z]})
    return rows


def test_synthetic_b3_passes():
    check_ends_on(synthetic(), "B3")


def test_rejects_log_ending_on_b2():
    with pytest.raises(AssertionError, match="last level record is B2"):
        check_ends_on(synthetic(end="B2"), "B3")


def test_rejects_pose_not_on_b3_despite_label():
    with pytest.raises(AssertionError, match="is on B2, not B3"):
        check_ends_on(synthetic(z_floor="B2"), "B3")


def test_rejects_pose_on_ramp_height():
    rows = synthetic()
    rows[-2]["pos"][2] = (LEVEL_Z["B2"] + LEVEL_Z["B3"]) / 2 + RIDE
    with pytest.raises(AssertionError, match="is on None"):
        check_ends_on(rows, "B3")


def test_real_b3_run_ends_on_b3(tmp_path, monkeypatch):
    from tools.run_b2 import run

    monkeypatch.setenv("GEMINI_MODE", "off")
    _, path = run(seed=0, floor="B3", out_dir=tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    check_ends_on(rows, "B3")
