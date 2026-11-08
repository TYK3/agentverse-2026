"""TICK-COVERAGE-B1: a real B1 run log covers every sim tick.

coord/CONTRACT.md puts the every-sim-tick rule on pose: ``responder/pose``
at 10 Hz (E2, the Responder's actual pose). The B1 runner on main is
``tools/run_b2.py --floor B1``. Its pose samples are the records with
``kind == "pose"`` (``t``, ``pos``, ``state``, ``level``, ``cell``). Level,
plan, shift and summary lines are events, so the every-tick check is those
pose times.

``DT`` is ``sim.demo_descent.DT``, the step ``tools.run_b2.run`` passes to
``LevelWorld.tick``.
"""

import itertools
import json

import pytest

TOL = 1e-6


def pose_times(rows):
    return [row["t"] for row in rows if row["kind"] == "pose"]


def coverage_problems(rows, dt):
    """Why pose sim times fail to step by ``dt`` from the run start to its end."""
    times = pose_times(rows)
    start, end = rows[0]["t"], rows[-1]["t"]
    diffs = [b - a for a, b in itertools.pairwise(times)]
    intervals = sorted({round(d, 6) for d in diffs})
    problems = []
    if not times:
        problems.append("no pose records")
    if times and abs(times[0] - start) > TOL:
        problems.append(f"first pose {times[0]} differs from the run start {start}")
    if times and abs(times[-1] - end) > TOL:
        problems.append(f"last pose {times[-1]} differs from the run end {end}")
    if len(times) < 2:
        problems.append("fewer than two pose times")
    off = [d for d in diffs if abs(d - dt) > TOL]
    if off:
        problems.append(
            f"{len(off)} consecutive step(s) are not DT={dt} within {TOL} "
            f"(gaps, duplicates or backwards steps); observed intervals {intervals}"
        )
    return problems


def test_b1_pose_log_covers_every_tick(tmp_path, monkeypatch):
    pytest.importorskip("mujoco")
    from sim.demo_descent import DT

    monkeypatch.setenv("GEMINI_MODE", "off")
    from tools.run_b2 import run

    _verdict, path = run(seed=0, floor="B1", out_dir=tmp_path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    problems = coverage_problems(rows, DT)
    assert not problems, (
        f"pose sim times do not cover every {DT} s tick from {rows[0]['t']} "
        f"to {rows[-1]['t']} ({len(pose_times(rows))} poses): " + "; ".join(problems)
    )
