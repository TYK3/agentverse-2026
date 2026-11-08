"""FIND-DESCEND: the Scout locates the survivor from its own sensors, then descends to it, in a real log.

A real L1 -> ground -> B1 run (sim.demo_descent's closed loop: LevelWorld physics, perception.levels,
planner.levels; nothing scripted). Every sensors/scout frame the sim produces for the Scout also goes
to perception.casualties.Casualties with vision off (GEMINI_MODE=off: thermal and sound clues only, no
camera model), and each casualty estimate is logged with the Scout's level and pose. The log is
written to jsonl and read back, and the checks run on what it says:
  - find: the Scout's own sensors produce an estimate of c1 (clues from thermal and/or sound only);
  - then descend: that first estimate comes while the Scout is still above B1 (on the way down), and
    after it the Scout stands on B1 and stops by the casualty;
  - the estimate is close to the survivor: within LOCATE_TOL of c1's marker and of where the Scout
    stopped.
c1 is the only casualty the sim's sensors model (World.casualty_geom), so this is B1 only.
"""

import json
import math

import pytest

pytest.importorskip("mujoco")

LOCATE_TOL = 1.0      # metres: today's estimate settles about 0.66 m from c1's marker


@pytest.fixture(scope="module")
def log(tmp_path_factory, monkeypatch_module):
    from perception.casualties import Casualties
    from sim import levels
    from sim.demo_descent import run

    cas = Casualties(vision_on=lambda: False)
    records = []
    original = levels.LevelWorld.sensors_message

    def tee(self, camera=True):
        data = original(self, camera=camera)
        records.append({"t": round(self.t, 2), "kind": "pose", "level": self.level(),
                        "pos": [round(float(v), 3) for v in self.pos]})
        if cas.on_sensors(data):
            for c in cas.message():
                records.append({"t": round(self.t, 2), "kind": "casualty", "level": self.level(), "id": c["id"],
                                "pos": c["pos"], "confidence": c["confidence"], "clues": c["clues"]})
        return data

    monkeypatch_module.setattr(levels.LevelWorld, "sensors_message", tee)
    out = run(max_t=400.0, floor="B1")
    world = levels.LevelWorld(render=False)
    truth = [round(float(v), 3) for v in world.d.geom_xpos[world.casualty_geom]]
    records.append({"t": out["t"], "kind": "summary", "reached": out["reached"], "final_pos": out["final_pos"],
                    "levels": out["levels"], "c1_marker": truth})
    path = tmp_path_factory.mktemp("find") / "find-descend-b1.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def first(records, kind, pred=lambda r: True):
    return next((r for r in records if r["kind"] == kind and pred(r)), None)


def test_the_scout_finds_c1_from_its_own_sensors(log):
    found = first(log, "casualty")
    assert found is not None, "no casualty estimate in the whole run"
    assert found["clues"] and set(found["clues"]) <= {"thermal", "sound"}      # no vision: own sensors only


def test_it_finds_before_it_reaches_b1_then_descends_to_the_casualty(log):
    found = first(log, "casualty")
    on_b1 = first(log, "pose", lambda r: r["level"] == "B1")
    summary = first(log, "summary")
    assert found["level"] != "B1", f"first located on {found['level']}: no find-then-descend"
    assert on_b1 is not None and on_b1["t"] >= found["t"]
    assert summary["reached"] and summary["levels"] == ["L1", "ground", "B1"]


def test_the_estimate_is_near_the_survivor_and_where_the_scout_stopped(log):
    last = [r for r in log if r["kind"] == "casualty"][-1]
    summary = first(log, "summary")
    marker, stop = summary["c1_marker"], summary["final_pos"]
    assert math.dist(last["pos"][:2], marker[:2]) <= LOCATE_TOL
    assert math.dist(last["pos"][:2], stop[:2]) <= LOCATE_TOL
    assert abs(last["pos"][2] - marker[2]) < 0.3                               # on B1, not a floor above
