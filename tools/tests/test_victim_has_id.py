"""VICTIM-HAS-ID: every victim record in a real run log has an id.

The run: tools/run_levels.py's real chained rescue (seed 0: L1 down to c1 on B1, c2 on B2, c3 on B3), with
perception/casualties.py fed the Scout's sensors/scout frame every tick, as the live bus does at 10 Hz,
so its map/casualties messages are recorded beside the runner's own log. Nothing in the run is changed.

Two kinds of victim record, both checked:
- the runner's "leg" records (and its "reached <id> on <floor>" steps): each names a casualty id that is a
  real casualty body in the scene (LevelWorld.casualties), lying on that leg's floor;
- perception's map/casualties: every entry has a non-empty string id, unique within its message, the
  message is valid against the contract (coord.messages), and an id once given stays in every later
  list (a track is never dropped or renamed). Perception's ids are its own track numbers: they are not
  checked against the scene's names (in this run its c3 is first placed where the scene's c2 lies).
"""

import copy
import re

import pytest

pytest.importorskip("mujoco")    # a real sim run; CI's tools lane has no MuJoCo (the full job does)

import sim.levels as sl
from perception.casualties import Casualties
from tools import run_levels

try:
    from coord.messages import validate_payload
except ImportError:              # coord's pydantic is not installed: the shape checks below still run
    validate_payload = None

BODY_ABOVE_FLOOR = (0.0, 0.3)    # metres: a casualty lies on its floor (scene bodies are 0.12 m up)
STEP = re.compile(r"^reached (\S+) on (\S+)$")


@pytest.fixture(scope="module")
def run():
    """(runner records, [(t, map/casualties)], {id: [x, y, z]} of the scene's casualty bodies)."""
    seen, bodies = [], {}
    init, tick = sl.LevelWorld.__init__, sl.LevelWorld.tick

    def observe_init(world, *a, **k):
        init(world, *a, **k)
        world._victims = Casualties(clock=lambda: float(world.t), vision_on=False)
        for name, g, _ in world.casualties:
            bodies[name] = [float(v) for v in world.d.geom_xpos[g]]

    def observe_tick(world, dt=0.1):
        events = tick(world, dt)
        if world._victims.on_sensors(world.sensors_message(camera=False)):
            seen.append((round(float(world.t), 1), world._victims.message()))
        return events

    with pytest.MonkeyPatch.context() as observe:
        observe.setattr(sl.LevelWorld, "__init__", observe_init)
        observe.setattr(sl.LevelWorld, "tick", observe_tick)
        records = run_levels.run(0)
    return records, seen, bodies


def assert_legs_name_victims(records, bodies):
    legs = [r for r in records if r["kind"] == "leg"]
    assert legs, "a real rescue run has legs"
    for leg in legs:
        vid = leg.get("casualty")
        assert isinstance(vid, str) and vid, f"leg to {leg.get('floor')} has no casualty id"
        assert vid in bodies, f"leg names {vid}, not a casualty in the scene"
        dz = bodies[vid][2] - sl.LEVEL_Z[leg["floor"]]
        assert BODY_ABOVE_FLOOR[0] <= dz <= BODY_ABOVE_FLOOR[1], f"{vid} is not on {leg['floor']} ({dz:.2f} m)"
    for step in (r for r in records if r["kind"] == "step"):
        m = STEP.match(step["name"])
        if m:
            assert m[1] in bodies and any(leg["casualty"] == m[1] and leg["floor"] == m[2] for leg in legs), step
    assert len({leg["casualty"] for leg in legs}) == len(legs), "two legs name the same victim"


def assert_perception_victims_have_ids(seen):
    assert seen, "perception located no one in a real run"
    known = []
    for t, msg in seen:
        ids = [c.get("id") for c in msg]
        assert all(isinstance(i, str) and i for i in ids), f"a victim at {t} s has no id: {ids}"
        assert len(set(ids)) == len(ids), f"two victims share an id at {t} s: {ids}"
        assert set(known) <= set(ids), f"at {t} s a victim id was dropped: had {known}, now {ids}"
        known = ids
        if validate_payload:
            validate_payload("map/casualties", msg)


def test_the_real_run_passes(run):
    records, _, bodies = run
    failed = [r["name"] for r in records if r["kind"] == "step" and not r["ok"]]
    assert failed == []
    assert sorted(bodies) == ["c1", "c2", "c3"]


def test_every_leg_names_a_real_victim_on_its_floor(run):
    records, _, bodies = run
    assert_legs_name_victims(records, bodies)
    assert [(r["floor"], r["casualty"]) for r in records if r["kind"] == "leg"] == \
        [("B1", "c1"), ("B2", "c2"), ("B3", "c3")]


def test_every_victim_perception_reports_has_an_id(run):
    _, seen, _ = run
    assert_perception_victims_have_ids(seen)
    assert len(seen) > 100
    assert {c["id"] for c in seen[-1][1]} == {"c1", "c2", "c3"}


@pytest.mark.parametrize("mutation", ["no_id", "empty_id", "unknown_id", "wrong_floor", "same_victim_twice"])
def test_broken_legs_are_rejected(run, mutation):
    records, _, bodies = copy.deepcopy(run)
    assert_legs_name_victims(records, bodies)
    leg = next(r for r in records if r["kind"] == "leg" and r["floor"] == "B2")
    if mutation == "no_id":
        del leg["casualty"]
    elif mutation == "empty_id":
        leg["casualty"] = ""
    elif mutation == "unknown_id":
        leg["casualty"] = "c9"
    elif mutation == "wrong_floor":
        leg["floor"] = "B3"
    else:
        leg["casualty"] = "c1"
    with pytest.raises(AssertionError):
        assert_legs_name_victims(records, bodies)


@pytest.mark.parametrize("mutation", ["no_id", "empty_id", "shared_id", "dropped_id"])
def test_broken_perception_reports_are_rejected(run, mutation):
    _, seen, _ = copy.deepcopy(run)
    assert_perception_victims_have_ids(seen)
    t, msg = seen[-1]
    if mutation == "no_id":
        del msg[0]["id"]
    elif mutation == "empty_id":
        msg[0]["id"] = ""
    elif mutation == "shared_id":
        msg[1]["id"] = msg[0]["id"]
    else:
        seen[-1] = (t, msg[1:])
    with pytest.raises(AssertionError):
        assert_perception_victims_have_ids(seen)
