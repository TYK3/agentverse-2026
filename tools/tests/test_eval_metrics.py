"""Synthetic traces verify scoring, not benchmark performance."""

import pytest

from tools.eval_metrics import headline, measure


def trace(events, completed=True):
    return {"seed": 0, "planner": "naive", "goal": [2, 0, 0], "events": events,
            "completed": completed, "backend": "synthetic-test", "scenario_sha256": "test"}


def pos(t, x):
    return {"t": t, "kind": "position", "cell": [x, 0, 0]}


def collapse(t, x):
    return {"t": t, "kind": "collapsed", "cells": [[x, 0, 0]]}


@pytest.mark.parametrize("events,count", [
    ([pos(0, 0), collapse(1, 1), pos(2, 1), pos(3, 2)], 1),
    ([pos(0, 0), pos(1, 1), collapse(2, 1), pos(3, 2)], 1),
    ([pos(0, 0), pos(1, 1), pos(2, 2), collapse(3, 1)], 0),
    ([pos(0, 0), collapse(1, 1), pos(1, 1), pos(2, 2)], 1),
    ([pos(0, 0), pos(1, 1), collapse(1, 1), pos(2, 2)], 1),
    ([pos(0, 0), collapse(1, 1), pos(2, 1), pos(3, 0), pos(4, 1), pos(5, 2)], 1),
])
def test_unsafe_entry_is_temporal_and_unique(events, count):
    result = measure(trace(events))
    assert result.reached_casualty
    assert result.unsafe_cells_entered == count
    assert result.safe_success == (count == 0)


def test_arrival_requires_observed_goal_position():
    result = measure(trace([pos(0, 0), {"t": 1, "kind": "reached"}]))
    assert result.reached_casualty is False
    assert result.time_to_casualty_s is None
    assert result.safe_success is False


def test_duplicate_routes_and_answers_do_not_inflate_counts():
    events = [pos(0, 0)] + [
        {"t": 1, "kind": "route", "id": rid} for rid in ["r1", "r1", "r2"]
    ] + [{"t": 2, "kind": "approval", "id": "g1", "approved": True}] * 2 + [pos(3, 2)]
    result = measure(trace(events))
    assert result.replans == 1
    assert result.human_approvals == 1
    assert result.time_to_casualty_s == 3


def test_missing_telemetry_is_not_measured_as_zero():
    result = measure(trace([], completed=True))
    assert not result.completed
    assert result.safe_success is None
    assert result.reached_casualty is None
    assert result.unsafe_cells_entered is None
    assert headline([result], "naive")["safe_success_rate"] is None


@pytest.mark.parametrize("times", [[1, 0], [0, float("nan")], [0, -1]])
def test_bad_trace_clock_is_rejected(times):
    with pytest.raises(ValueError):
        measure(trace([pos(times[0], 0), pos(times[1], 2)]))


def test_partial_coverage_is_explicit():
    rows = [measure(trace([pos(0, 0), pos(2, 2)])), measure(trace([], completed=False))]
    assert headline(rows, "naive") == {"planner": "naive", "safe_successes": 1,
        "measured_trials": 1, "attempted_trials": 2, "safe_success_rate": 1.0}
