"""LOG-HAS-ROBOT: every record in a run log that is about a robot says which robot.

Two log shapes are on main (coord/run_log_schema.json):
  - bus envelopes {"topic", "data"} (sim/recorder.py, tools/demo60.py): the robot is in the topic
    (sensors/scout, scout/goto, responder/pose, responder/action) or, for route/proposed, in data.robot;
  - tools/run_b2.py records {"t", "kind", ...}: pose, plan, level, shift and mapped are all about the Scout,
    but no record names it (the shift's "scout" field is the Scout's position, not a robot field), and the
    schema's pose and plan records forbid extra fields (additionalProperties: false).

robot_of() resolves a record's robot from an explicit "robot" field, else from the topic. The real Scout
recordings, every coord/fixtures envelope about a robot and the topic table pass. The real B2 run_b2 log is a
strict xfail: it flips once run_b2.py writes "robot": "scout" on those records and coord/run_log_schema.json
allows it (a tools + coord change, not this test's).
"""

import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
RECORDINGS = sorted((ROOT / "sim" / "recordings").glob("*.jsonl"))
FIXTURES = ROOT / "coord" / "fixtures"
REAL_B2 = ROOT / "console" / "tests" / "fixtures" / "b2-seed0.jsonl"
ROBOTS = {"scout", "responder"}
TOPIC_ROBOT = {"sensors/scout": "scout", "scout/goto": "scout",
               "responder/pose": "responder", "responder/action": "responder"}
FIELD_TOPICS = {"route/proposed"}                         # the robot is data.robot
RUN_B2_ROBOT_KINDS = {"pose", "plan", "level", "shift", "mapped"}   # run_b2 records about the Scout


def load(path):
    return [json.loads(line) for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines() if line]


def robot_of(record):
    """The robot a log record is about, or None if the record does not say."""
    if "topic" in record:
        topic, data = record["topic"], record.get("data")
        if topic in FIELD_TOPICS:
            robot = data.get("robot") if isinstance(data, dict) else None
            return robot if robot in ROBOTS else None
        return TOPIC_ROBOT.get(topic)
    robot = record.get("robot")
    return robot if robot in ROBOTS else None


def about_a_robot(record):
    if "topic" in record:
        return record["topic"] in TOPIC_ROBOT or record["topic"] in FIELD_TOPICS
    return record.get("kind") in RUN_B2_ROBOT_KINDS


def unnamed(records):
    return [(i, r.get("topic", r.get("kind"))) for i, r in enumerate(records) if about_a_robot(r) and robot_of(r) is None]


@pytest.mark.parametrize("path", RECORDINGS, ids=[p.name for p in RECORDINGS])
def test_real_scout_recordings_name_their_robot(path):
    records = load(path)
    assert records and unnamed(records) == []
    assert {robot_of(r) for r in records if about_a_robot(r)} == {"scout"}


def test_every_robot_fixture_names_its_robot():
    envelopes = [json.loads(p.read_text()) for p in sorted(FIXTURES.glob("*.json"))]
    robot_ones = [e for e in envelopes if about_a_robot(e)]
    assert {e["topic"] for e in robot_ones} == set(TOPIC_ROBOT) | FIELD_TOPICS
    assert unnamed(robot_ones) == []


def test_the_topic_table_covers_every_robot_topic():
    """Every contract topic naming a robot in its path is in the table, so a new one cannot slip by."""
    from coord.messages import TOPICS

    robot_topics = {t for t in TOPICS if ROBOTS & set(t.split("/"))}
    assert robot_topics <= set(TOPIC_ROBOT) | FIELD_TOPICS, robot_topics - set(TOPIC_ROBOT)


@pytest.mark.parametrize("record", [
    {"topic": "route/proposed", "data": {"id": "r1", "cells": [], "goal": "g", "model": "m"}},   # no robot
    {"topic": "route/proposed", "data": {"id": "r1", "robot": "drone", "cells": []}},           # unknown robot
    {"t": 0, "kind": "pose", "pos": [0, 0, 0], "state": "idle", "level": "L1", "cell": [0, 0, 0]},
    {"t": 0, "kind": "plan", "status": "ok", "why": "route", "cells": [], "robot": "Scout"},     # wrong case
])
def test_a_record_that_does_not_name_its_robot_is_caught(record):
    assert unnamed([record]) == [(0, record.get("topic", record.get("kind")))]


def test_a_named_run_b2_record_resolves():
    assert robot_of({"t": 0, "kind": "pose", "robot": "scout"}) == "scout"


@pytest.mark.xfail(strict=True, reason="run_b2.py writes no robot on pose/plan/level/shift/mapped, and "
                                       "coord/run_log_schema.json's pose and plan forbid extra fields")
def test_the_real_b2_run_log_names_its_robot():
    records = load(REAL_B2)
    assert unnamed(records) == [], f"{len(unnamed(records))} Scout records without a robot, first {unnamed(records)[:3]}"
