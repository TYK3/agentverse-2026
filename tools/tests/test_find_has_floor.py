"""FIND-HAS-FLOOR: every casualty find names the floor it is on.

A find is one entry of map/casualties from perception/casualties.py: {"id", "pos": [x, y, z], ...}. The
contract has no floor field, so a find names its floor by its height: z is the Scout's own sensor height at
the find's last update, so on floor F it is LEVEL_Z[F] + RIDE. floor_of() turns a height into that name (or
None between floors). One real L1 -> B3 descent (sim.demo_descent, nothing scripted but the goal, about 60 s)
feeds every sensors/scout frame to Casualties with vision off (GEMINI_MODE=off: thermal and sound only), as
DESCEND-AFTER-LOCATE (#335) does, and records every published map/casualties. Truth (the casualty markers in
sim/scenes/levels.xml) is used only to score.

  - pass: floor_of names each floor's height and nothing in between;
  - pass: every find published while the Scout stands on a floor names a floor;
  - pass: c2's find names B2 and lies within LOCATE of the c2 marker;
  - strict xfail, finding 1: finds updated from a ramp carry the ramp's height and name no floor
    (first at 64.7 s, z -0.477, between ground and B1): _update() copies the Scout's z on every update;
  - strict xfail, finding 2: at the end not every floor's casualty has a find naming its floor: B1's track
    is merged into B3's (plan-view MERGE only: c1 and c3 are 0.1 m apart across floors), so it ends named B3.
    Same cause as #335's finding 2; #362 (CASUALTY-PER-FLOOR) is the fix in progress.
"""

import math

import pytest

pytest.importorskip("mujoco")      # sim.levels imports MuJoCo: skip, not error, in the tools CI job

from sim.levels import LEVEL_Z, RIDE

FLOOR_BAND = 0.02      # metres: a find's height within this of LEVEL_Z + RIDE names that floor
LOCATE = 1.0           # metres in plan view: FIND-DESCEND's tolerance
MARKERS = {"B1": "casualty_c1", "B2": "casualty_c2", "B3": "casualty_c3"}


def floor_of(z):
    """The floor a find's height names, or None if it is between floors."""
    return next((name for name, h in LEVEL_Z.items() if abs(z - RIDE - h) < FLOOR_BAND), None)


def test_floor_of_names_each_floor_and_nothing_between():
    for name, h in LEVEL_Z.items():
        assert floor_of(h + RIDE) == name
        assert floor_of(h + RIDE + 0.015) == name
    assert floor_of(LEVEL_Z["B1"] + RIDE + 0.3) is None          # halfway up a ramp
    assert floor_of(-0.477) is None                              # the first real c1 find, from R1


@pytest.fixture(scope="module")
def run_log():
    pytest.importorskip("mujoco")
    from perception.casualties import Casualties
    from sim import levels
    from sim.demo_descent import run

    cas = Casualties(vision_on=lambda: False)
    updates = []
    original = levels.LevelWorld.sensors_message

    def tee(self, camera=True):
        data = original(self, camera=camera)
        if cas.on_sensors(data):
            updates.append({"t": round(self.t, 2), "level": self.level(), "finds": cas.message()})
        return data

    mp = pytest.MonkeyPatch()
    mp.setattr(levels.LevelWorld, "sensors_message", tee)
    try:
        result = run(max_t=400.0, floor="B3")
    finally:
        mp.undo()
    assert result["reached"], result["log"][-5:]
    world = levels.LevelWorld(render=False)
    markers = {f: [float(v) for v in world.m.body(b).pos] for f, b in MARKERS.items()}
    assert updates
    return updates, markers


def test_every_find_published_on_a_floor_names_a_floor(run_log):
    updates, _ = run_log
    on_floor = [(u["t"], f["id"], f["pos"]) for u in updates if u["level"] != "ramp" for f in u["finds"]]
    assert len(on_floor) > 100
    unnamed = [x for x in on_floor if floor_of(x[2][2]) is None]
    assert not unnamed, f"{len(unnamed)} finds on a floor name none, first {unnamed[:3]}"


def test_c2_is_found_on_b2(run_log):
    updates, markers = run_log
    final = updates[-1]["finds"]
    near = [f for f in final if math.dist(f["pos"][:2], markers["B2"][:2]) < LOCATE]
    assert near and all(floor_of(f["pos"][2]) == "B2" for f in near), (final, markers["B2"])


@pytest.mark.xfail(strict=True, reason="perception/casualties.py _update() copies the Scout's z on every "
                                       "update, so a find updated from a ramp names no floor")
def test_every_published_find_names_a_floor(run_log):
    updates, _ = run_log
    unnamed = [(u["t"], f["id"], f["pos"]) for u in updates for f in u["finds"] if floor_of(f["pos"][2]) is None]
    assert not unnamed, f"{len(unnamed)} finds name no floor, first {unnamed[:3]}"


@pytest.mark.xfail(strict=True, reason="tracks merge across floors by plan-view distance (c1/c3 0.1 m apart): "
                                       "B1's find ends named B3 (#335 finding 2, #362)")
def test_each_floors_casualty_ends_with_a_find_naming_its_floor(run_log):
    updates, markers = run_log
    final = updates[-1]["finds"]
    missing = [floor for floor, m in markers.items()
               if not any(floor_of(f["pos"][2]) == floor and math.dist(f["pos"][:2], m[:2]) < LOCATE for f in final)]
    assert not missing, f"no final find names {missing}; finds {[(f['id'], f['pos']) for f in final]}"
