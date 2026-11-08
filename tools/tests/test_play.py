"""CLI smoke tests for tools/play.py (ref TESTBED-2). No viewer window is opened."""

import os
import pathlib
import subprocess
import sys

import pytest

from tools import play

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_parse_defaults_and_flags():
    a = play.parse([])
    assert a.rescue is False and a.no_viewer is False and a.max_t == 600.0
    a = play.parse(["--rescue", "--no-viewer", "--max-t", "30"])
    assert a.rescue and a.no_viewer and a.max_t == 30.0
    a = play.parse(["--headless"])
    assert a.no_viewer and not a.rescue
    with pytest.raises(SystemExit):
        play.parse(["--max-t", "0"])


def test_want_viewer_respects_flag_and_display():
    assert play.want_viewer(True, {"DISPLAY": ":0"}) is False
    assert play.want_viewer(False, {}) is False
    assert play.want_viewer(False, {"DISPLAY": ":0"}) is True
    assert play.want_viewer(False, {"WAYLAND_DISPLAY": "wayland-0"}) is True


def test_headless_play_exits_without_opening_a_window():
    """python tools/play.py --no-viewer must load the levels scene and exit."""
    pytest.importorskip("mujoco")
    env = dict(os.environ, GEMINI_MODE="off")
    proc = subprocess.run(
        [sys.executable, "tools/play.py", "--no-viewer"],
        check=False, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "levels scene loaded" in out
    assert "Scout on L1" in out


def test_headless_rescue_with_tiny_budget_exits():
    """--rescue --no-viewer must not hang on a window, even when the Scout cannot finish."""
    pytest.importorskip("mujoco")
    env = dict(os.environ, GEMINI_MODE="off")
    proc = subprocess.run(
        [sys.executable, "tools/play.py", "--rescue", "--no-viewer", "--max-t", "0.5"],
        check=False, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "levels scene loaded" in proc.stdout
    assert "result:" in proc.stdout
    assert "'reached': False" in proc.stdout
