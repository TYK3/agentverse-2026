"""Rescue regression for tools/play.py --rescue (ref TESTBED-3). No viewer window is opened."""

import os
import pathlib
import subprocess
import sys

import pytest

from tools import play

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _has_in_order(seq, required):
    """True when every item in *required* appears in *seq* in that order (extras allowed)."""
    it = iter(seq)
    return all(item in it for item in required)


def test_run_rescue_reaches_b1():
    """play.run_rescue() completes a full B1 rescue on the levels scene."""
    pytest.importorskip("mujoco")
    os.environ["GEMINI_MODE"] = "off"
    result = play.run_rescue(verbose=False)

    assert result["reached"] is True
    assert result["t"] == pytest.approx(88.7, abs=0.5)
    assert _has_in_order(result["levels"], ["L1", "ground", "B1"])
    assert result["max_jump"] < 0.05
    assert result["responder_route"] == "ok"
    assert result["route_k"] == (12, -12)

    drive = result["responder_drive"]
    assert drive["driven"] is True
    assert drive.get("state")  # #267 put a responder body in the levels scene, so the route is driven


def test_cli_rescue_no_viewer_prints_reached():
    """python tools/play.py --rescue --no-viewer prints the result and exits 0 when reached."""
    pytest.importorskip("mujoco")
    env = dict(os.environ, GEMINI_MODE="off")
    proc = subprocess.run(
        [sys.executable, "tools/play.py", "--rescue", "--no-viewer"],
        check=False, cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "levels scene loaded" in out
    assert "result:" in out
    assert "'reached': True" in out
