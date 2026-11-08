"""DESCEND-AFTER-LOCATE: the Scout locates each basement casualty from its own sensors, and descends to its
floor after locating it.

One real L1 -> ground -> B1 -> B2 -> B3 run (sim.demo_descent to c3, about 60 s; nothing scripted but the
goal). As in FIND-DESCEND (#231), every sensors/scout frame also goes to perception.casualties.Casualties with
vision off (GEMINI_MODE=off: thermal and sound only), and each estimate is logged with the Scout's level.
The log is written to jsonl and read back. Truth (the casualty markers in sim/scenes/levels.xml) is used only
to score the estimates.

Per floor, the casualty there (B1 c1, B2 c2, B3 c3) counts as located when an estimate lands within LOCATE
of its marker, at its floor's height.
  - pass: each one is located by the Scout's own sensors on this run.
  - pass: c1 is located from the ramp before the Scout reaches B1 (64.7 s, on B1 at 65.9 s).
  - strict xfail, finding 1: c2 and c3 are located only after the Scout reaches their floor (B2: on it at
    143.0 s, located 173.9 s; B3: 217.1 / 221.4). The descent follows the fixed goal (sim/demo_descent.py
    GOALS), not a find.
  - strict xfail, finding 2: the three casualties are reported under one id ("c1"). perception/casualties.py
    merges tracks by plan-view distance only (MERGE 0.6 m), and c1 (0.45, 1.9) on B1 and c3 (0.45, 2.0) on
    B3 are 0.1 m apart in plan view; its one provisional track also follows thermal points on any floor.
"""

import json
import math

import pytest

pytest.importorskip("mujoco")

FLOORS = {"B1": "c1", "B2": "c2", "B3": "c3"}
LOCATE = 1.0           # metres in plan view: FIND-DESCEND's tolerance (estimates settle about 0.66 m off)
LEVEL_TOL = 0.35       # metres in height: an estimate on the casualty's floor, not the one above or below


@pytest.fixture(scope="module")
def log(tmp_path_factory):
    from perception.casualties import Casualties
    from sim import levels
    from sim.demo_descent import run

    cas = Casualties(vision_on=lambda: False)
    records = []
    original = levels.LevelWorld.sensors_message

    def tee(self, camera=True):
        data = original(self, camera=camera)
        records.append({"t": round(self.t, 2), "kind": "pose", "level": self.level()})
        if cas.on_sensors(data):
            for c in cas.message():
                records.append({"t": round(self.t, 2), "kind": "casualty", "level": self.level(), "id": c["id"],
                                "pos": c["pos"], "clues": c["clues"]})
        return data

    mp = pytest.MonkeyPatch()
    mp.setattr(levels.LevelWorld, "sensors_message", tee)
    try:
        out = run(max_t=500.0, floor="B3")
    finally:
        mp.undo()
    world = levels.LevelWorld(render=False)
    truth = {name: [round(float(v), 3) for v in world.d.geom_xpos[geom]] for name, geom, _ in world.casualties}
    records.append({"t": out["t"], "kind": "summary", "reached": out["reached"], "levels": out["levels"],
                    "markers": truth})
    path = tmp_path_factory.mktemp("locate") / "descend-after-locate-b3.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def summary(log):
    return log[-1]


def near(log, name):
    """Estimates that land on casualty `name`: within LOCATE in plan view, at its floor's height."""
    m = summary(log)["markers"][name]
    return [r for r in log if r["kind"] == "casualty"
            and math.dist(r["pos"][:2], m[:2]) < LOCATE and abs(r["pos"][2] - m[2]) < LEVEL_TOL]


def arrival(log, floor):
    return next(r["t"] for r in log if r["kind"] == "pose" and r["level"] == floor)


def test_the_run_descends_through_every_basement_to_c3(log):
    s = summary(log)
    assert s["reached"] and s["levels"] == ["L1", "ground", "B1", "B2", "B3"]
    assert set(FLOORS.values()) <= set(s["markers"])


@pytest.mark.parametrize("floor", FLOORS)
def test_each_basement_casualty_is_located_by_the_scouts_own_sensors(log, floor):
    hits = near(log, FLOORS[floor])
    assert hits, f"no estimate within {LOCATE} m of {FLOORS[floor]} on {floor}"
    assert set(hits[0]["clues"]) <= {"thermal", "sound"}, "vision is off: own sensors only"


LATE = pytest.mark.xfail(strict=True, reason="finding 1: the descent follows the fixed goal; c2/c3 are located only "
                         "after the Scout reaches their floor")


@pytest.mark.parametrize("floor", ["B1", pytest.param("B2", marks=LATE), pytest.param("B3", marks=LATE)])
def test_each_casualty_is_located_before_the_scout_descends_to_its_floor(log, floor):
    first = near(log, FLOORS[floor])[0]
    assert first["t"] < arrival(log, floor), f"located at {first['t']} s, on {floor} since {arrival(log, floor)} s"


@pytest.mark.xfail(strict=True, reason="finding 2: perception/casualties.py merges casualties on different floors "
                   "(plan-view MERGE only) into one id")
def test_each_basement_casualty_keeps_its_own_id(log):
    ids = {name: {r["id"] for r in near(log, name)} for name in FLOORS.values()}
    owners = [i for found in ids.values() for i in found]
    assert len(owners) == len(set(owners)), f"one id spans casualties on different floors: {ids}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
