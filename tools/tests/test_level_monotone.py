"""LEVEL-MONOTONE: real chained-run floor observations never go backwards.

Run the real sim/perception/planner chain, not a synthetic sequence or fixed
waypoints. Ground is an actual intermediate floor between L1 and B1; ramps are
transitions, not floors. Check recorded order as emitted, never sorted order.
"""

from itertools import pairwise

from tools.run_levels import run

ORDER = ["L1", "ground", "B1", "B2", "B3"]


def assert_monotone_floor_observations(observations, source):
    """Allow dwelling on a floor, but never going back or skipping one."""
    assert observations, source
    ranks = {floor: index for index, floor in enumerate(ORDER)}
    assert all(r["level"] in ranks for r in observations), (source, observations)
    assert observations[0]["level"] == "L1", (source, observations[0])
    assert observations[-1]["level"] == "B3", (source, observations[-1])
    for before, after in pairwise(observations):
        assert before["t"] <= after["t"], (source, before, after)
        change = ranks[after["level"]] - ranks[before["level"]]
        assert change in (0, 1), (source, "backward or skipped floor", before, after)
    # Explicitly cover the assignment's L1 > B1 > B2 > B3 sequence as well as
    # the real ground-floor transition; repeated pose samples are just dwell.
    visits = []
    for record in observations:
        if not visits or record["level"] != visits[-1]:
            visits.append(record["level"])
    assert visits == ORDER, (source, visits)
    assert [floor for floor in visits if floor != "ground"] == ["L1", "B1", "B2", "B3"]


def test_real_chained_run_has_monotone_floor_events_and_pose_observations():
    records = run(seed=0, max_t=500.0)
    legs = [r for r in records if r["kind"] == "leg"]
    assert [r["floor"] for r in legs] == ["B1", "B2", "B3"]
    assert all(r["reached"] is True for r in legs), legs

    events = [r for r in records if r["kind"] == "level"]
    assert [r["level"] for r in events] == ORDER, events
    assert_monotone_floor_observations(events, "level events")
    # Inspect every logged floor observation, not just successful-leg summaries:
    # a brief return to B1 after B2 must fail even if the run later reaches B3.
    poses = [r for r in records if r["kind"] == "pose" and r["level"] != "ramp"]
    assert len(poses) > len(ORDER)
    assert_monotone_floor_observations(poses, "pose observations")
