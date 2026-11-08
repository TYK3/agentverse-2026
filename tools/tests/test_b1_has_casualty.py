"""B1-HAS-CASUALTY: basement B1 has a casualty (c1), and a real B1 run log ends beside it on B1.

The scene is checked for a casualty_c1 body lying on the B1 floor. The goal tools/run_b2.py drives to
(sim/demo_descent.py GOALS["B1"]) must be next to c1 on B1. One real `run_b2.run(floor="B1")` log, about
30 s, must end on B1 within reach of c1, and its own verdict must say the casualty was reached.

Strict xfail, a finding: the log never names the casualty. No record says "c1"; the goal is a fixed point
"beside" it, so a log alone cannot say who was reached. Closing it needs run_b2.py (tools/, its owner) to
write the casualty id, for example on the summary, and coord/run_log_schema.json (the lead) to allow it.
"""

import json
import math
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
REACH = 0.15            # run_b2's "reached": within 0.15 m of the goal
BESIDE = 0.5            # metres from the casualty's body (not its centre) a responder can treat it from


def casualty_c1():
    """(centre xyz, distance(x, y) -> metres from c1's lying capsule body in plan view), from the scene."""
    mujoco = pytest.importorskip("mujoco")
    m = mujoco.MjModel.from_xml_path(str(ROOT / "sim" / "scenes" / "levels.xml"))
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    g = m.geom("c1_g").id
    radius, half = m.geom_size[g][:2]
    centre, axis = d.geom_xpos[g], d.geom_xmat[g].reshape(3, 3)[:, 2]
    a, b = centre - half * axis, centre + half * axis

    def distance(x, y):
        ab = b[:2] - a[:2]
        u = 0.0 if not ab.any() else max(0.0, min(1.0, float(((x, y) - a[:2]) @ ab / (ab @ ab))))
        near = a[:2] + u * ab
        return max(0.0, math.hypot(x - near[0], y - near[1]) - radius)

    return [float(v) for v in d.xpos[m.body("casualty_c1").id]], distance


@pytest.fixture(scope="module")
def log(tmp_path_factory):
    pytest.importorskip("mujoco")
    from tools import run_b2

    verdict, path = run_b2.run(seed=0, out_dir=tmp_path_factory.mktemp("b1"), floor="B1")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return records, verdict


def test_the_scene_has_a_casualty_lying_on_b1():
    from sim.levels import LEVEL_Z

    z = casualty_c1()[0][2]
    assert LEVEL_Z["B1"] < z < LEVEL_Z["B1"] + 0.3, f"c1 at z {z:.2f} is not on the B1 floor ({LEVEL_Z['B1']})"


def test_the_b1_goal_is_beside_c1_on_b1():
    from sim.demo_descent import GOALS
    from sim.levels import LEVEL_Z

    gx, gy, gz = GOALS["B1"]
    _, distance = casualty_c1()
    assert gz == LEVEL_Z["B1"]
    assert distance(gx, gy) + REACH <= BESIDE, f"goal {distance(gx, gy):.2f} m from c1's body"


def test_a_real_b1_run_ends_beside_c1_on_b1(log):
    records, verdict = log
    summary = next(r for r in records if r["kind"] == "summary")
    assert summary["floor"] == "B1" and summary["final_level"] == "B1"
    assert summary["reached"] is True
    _, distance = casualty_c1()
    fx, fy, _ = summary["final_pos"]
    assert distance(fx, fy) <= BESIDE, f"ended {distance(fx, fy):.2f} m from c1's body"
    assert verdict["steps"]["Scout reached the casualty on the target floor"]["ok"]


@pytest.mark.xfail(strict=True, reason="run_b2.py's log never names the casualty it drove to (no 'c1' in any record)")
def test_the_log_names_the_casualty_it_reached(log):
    records, _ = log
    assert any("c1" in json.dumps({k: v for k, v in r.items() if k != "steps"}) for r in records)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
