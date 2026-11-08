import copy

import pytest

from tools.eval_compare import compare, markdown


def pair():
    common = {"seed": 0, "goal": [2, 0, 0], "completed": True, "backend": "synthetic-test",
              "scenario_sha256": "same-scene", "source_sha256": {"sim/world.py": "same-source"},
              "sim_seconds": 60, "stand_ins": ["synthetic-test"], "casualty_pos": [2, 0, 0],
              "reach_distance_m": 0.45,
              "events": [{"t": 0, "kind": "position", "cell": [0, 0, 0], "pos": [0, 0, 0]}],
              "bus_messages": [{"t": 3, "topic": "map/casualties", "data": [{"id": "c1", "pos": [2, 0, 0]}]},
                               {"t": 4, "topic": "map/casualties", "data": [{"id": "c1", "pos": [2, 0, 0]}]}]}
    return [{**copy.deepcopy(common), "planner": name} for name in ("naive", "aftershock")]


def test_no_arrival_is_na_and_repeated_reports_do_not_inflate_discovery():
    result = compare(pair())
    assert result["results"][0]["casualties_found"] == 1
    assert result["results"][0]["median_arrival_s"] is None
    assert "N/A" in markdown(result)
    assert result["unsafe_entries_avoided"] == 0


def test_false_tracks_do_not_count_as_found_casualties():
    traces = pair()
    for trace in traces:
        trace["bus_messages"].insert(0, {"t": 1, "topic": "map/casualties",
                                          "data": [{"id": "false-track", "pos": [10, 0, 0]}]})
    result = compare(traces)
    assert result["results"][0]["casualties_found"] == 1
    assert result["results"][0]["reported_tracks"] == 2
    assert result["results"][0]["median_first_detection_s"] == 3


def test_unsafe_reduction_is_signed_not_clamped_to_success():
    traces = pair()
    traces[1]["events"] += [{"t": 5, "kind": "collapsed", "cells": [[1, 0, 0]]},
                             {"t": 6, "kind": "position", "cell": [1, 0, 0]}]
    assert compare(traces)["unsafe_entries_avoided"] == -1


def test_non_arrivals_do_not_reduce_median_arrival_time():
    traces = pair()
    extra = pair()
    for trace in extra:
        trace["seed"] = 1
    traces[0]["events"].append({"t": 8, "kind": "position", "cell": [2, 0, 0], "pos": [2, 0, 0]})
    result = compare(traces + extra)
    assert result["results"][0]["arrivals"] == 1
    assert result["results"][0]["median_arrival_s"] == 8


@pytest.mark.parametrize("defect", ["missing", "duplicate", "scenario", "source", "incomplete"])
def test_unpaired_or_untrustworthy_comparisons_fail(defect):
    traces = pair()
    if defect == "missing":
        traces.pop()
    elif defect == "duplicate":
        traces.append(traces[0])
    elif defect == "scenario":
        traces[1]["scenario_sha256"] = "different"
    elif defect == "source":
        traces[1]["source_sha256"] = {"sim/world.py": "different"}
    else:
        traces[1]["completed"] = False
    with pytest.raises(ValueError):
        compare(traces)
