"""Paired-run and output integration checks using an explicitly synthetic driver."""

import asyncio
import csv
import hashlib
import json

import pytest

from tools.eval import evaluate, parse
from tools.eval_grid import run_trial, scenario


async def trial(*, seed, planner):
    fingerprint = hashlib.sha256(str(seed).encode()).hexdigest()
    events = [{"t": 0, "kind": "position", "cell": [0, 0, 0]},
              {"t": 1, "kind": "collapsed", "cells": [[1, 0, 0]]}]
    if planner == "naive":
        events += [{"t": 2, "kind": "position", "cell": [1, 0, 0]}]
    events += [{"t": 3, "kind": "position", "cell": [2, 0, 0]}]
    return {"seed": seed, "planner": planner, "goal": [2, 0, 0], "events": events,
            "completed": True, "backend": "synthetic-test", "stand_ins": ["all-test-data"],
            "scenario_sha256": fingerprint}


def test_paired_runs_write_artifacts(tmp_path):
    args = parse(["--runs", "2", "--output", str(tmp_path)])
    assert asyncio.run(evaluate(args, trial)) == 0
    with (tmp_path / "results.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 4
    assert rows[0]["unsafe_cells_entered"] == "1"
    assert rows[1]["unsafe_cells_entered"] == "0"
    assert rows[0]["scenario_sha256"] == rows[1]["scenario_sha256"]
    assert (tmp_path / "safe_success.png").read_bytes().startswith(b"\x89PNG")
    assert len(list((tmp_path / "traces").glob("*.json"))) == 4
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["stand_ins"] == ["all-test-data"]
    assert "live full-system" in (tmp_path / "summary.md").read_text()


def test_mismatched_scenes_are_rejected(tmp_path):
    async def bad(**kw):
        result = await trial(**kw)
        result["scenario_sha256"] = result["planner"]
        return result

    with pytest.raises(ValueError, match="same scenario"):
        asyncio.run(evaluate(parse(["--runs", "1", "--output", str(tmp_path)]), bad))


@pytest.mark.parametrize("argv", [["--runs", "0"], ["--max-seconds", "900"],
                                 ["--trial-timeout", "0"]])
def test_invalid_cli_limits(argv):
    with pytest.raises(SystemExit):
        parse(argv)


def test_seed_varies_rubble_and_casualty_and_is_reproducible():
    assert scenario(7) == scenario(7)
    assert len({scenario(seed)[1] for seed in range(30)}) == 30
    assert len({tuple(scenario(seed)[0]["casualty"]) for seed in range(30)}) > 1
    assert len({str(scenario(seed)[0]["rubble"]) for seed in range(30)}) == 30


def test_grid_driver_labels_its_stand_ins():
    naive = asyncio.run(run_trial(seed=7, planner="naive"))
    aftershock = asyncio.run(run_trial(seed=7, planner="aftershock"))
    assert naive["scenario_sha256"] == aftershock["scenario_sha256"]
    assert "no-MuJoCo-verification" in aftershock["stand_ins"]
