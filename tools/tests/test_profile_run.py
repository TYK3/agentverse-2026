"""tools/profile_run.py with mocked subprocess and clock (no lanes start)."""

import asyncio
import json
import subprocess
import types
from collections import defaultdict

from tools import profile_run as pr


def test_rtf():
    assert pr.rtf([(0.0, 0.0), (10.0, 7.7)]) == 0.77
    assert pr.rtf([(1.0, 0.0)]) is None and pr.rtf([(1.0, 0.0), (1.0, 2.0)]) is None


def clock(values):
    it = iter(values)
    return lambda: next(it)


def test_timed_books_sync_and_async_to_lane():
    book = defaultdict(lambda: {"calls": 0, "ms": 0.0})

    def sync(data):
        return data

    async def coro(data):
        return data

    sync.__module__ = coro.__module__ = "perception.grid"
    assert pr.timed(sync, book, clock([0.0, 0.25]))(1) == 1
    assert asyncio.run(pr.timed(coro, book, clock([1.0, 1.5]))(2)) == 2
    assert book["perception"] == {"calls": 2, "ms": 750.0}


def child_line(rtf):
    return pr.MARK + json.dumps({"lanes": ["sim"], "rtf": rtf, "wall_s": 10.0, "sim_s": 7.7,
                                 "handlers": {"perception": {"calls": 5, "ms": 12.0, "share": 0.001}}})


def test_run_set_ok_fail_timeout():
    seen = []

    def ok(cmd, **kw):
        seen.append((cmd, kw))
        return types.SimpleNamespace(returncode=0, stdout="noise\n" + child_line(0.77), stderr="")
    r = pr.run_set("sim", ["sim"], 10, 1, 60, ok)
    assert r["status"] == "ok" and r["rtf"] == 0.77
    cmd, kw = seen[0]
    assert cmd[cmd.index("--child") + 1] == "sim" and kw["env"]["GEMINI_MODE"] == "off"

    bad = pr.run_set("sim", ["sim"], 10, 1, 60, lambda c, **k: types.SimpleNamespace(
        returncode=1, stdout="", stderr="Traceback\nImportError: mujoco"))
    assert bad["status"] == "fail" and "ImportError" in bad["reason"]

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])
    assert pr.run_set("sim", ["sim"], 10, 1, 60, slow)["status"] == "timeout"


def test_main_writes_report(tmp_path):
    out = tmp_path / "perf.md"
    ok = lambda c, **k: types.SimpleNamespace(returncode=0, stdout=child_line(0.9), stderr="")
    assert pr.main(["--duration", "10", "--output", str(out)], runner=ok) == 0
    md = out.read_text()
    assert "| sim (sim) | 0.90x | 7.7 | 10.0 | ok |" in md
    assert "| +voice (all) | perception | 5 | 12.0 | 0.001 |" in md
    fail = lambda c, **k: types.SimpleNamespace(returncode=2, stdout="", stderr="boom")
    assert pr.main(["--output", str(out)], runner=fail) == 1
    assert "fail: boom" in out.read_text()


class Grid:
    def add_sensors(self, data):
        return data


def test_timed_detail_per_handler_and_topic():
    book = defaultdict(lambda: {"calls": 0, "ms": 0.0})
    detail = defaultdict(lambda: {"calls": 0, "ms": 0.0, "max_ms": 0.0})
    g = Grid()
    wrapped = pr.timed(g.add_sensors, book, clock([0.0, 0.002, 1.0, 1.010]), detail, "sensors/scout")
    wrapped(1)
    wrapped(2)
    name = pr.handler_name(g.add_sensors)
    assert name.endswith("test_profile_run.Grid.add_sensors")
    d = detail[(name, "sensors/scout")]
    assert d["calls"] == 2 and round(d["ms"], 6) == 12.0 and round(d["max_ms"], 6) == 10.0


def test_per_handler_table_lane_first():
    row = {"set": "+voice (all)", "lanes": ["sim", "perception"], "wall_s": 20.0, "per_handler": [
        {"handler": "planner.route.RoutePlanner.update_map", "topic": "map/cells", "calls": 3,
         "ms": 900.0, "mean_ms": 300.0, "max_ms": 400.0, "share": 0.045},
        {"handler": "perception.hazards.Hazards.on_sensors", "topic": "sensors/scout", "calls": 10,
         "ms": 80.0, "mean_ms": 8.0, "max_ms": 40.0, "share": 0.004}]}
    lines = pr.per_handler_table([{"set": "sim"}, row])
    body = [ln for ln in lines if ln.startswith("| ") and "Handler" not in ln]
    assert body[0].startswith("| perception.hazards.Hazards.on_sensors | sensors/scout | 10 | 80.0 |")
    assert "perception handlers total 80.0 ms" in "\n".join(lines)
    assert pr.per_handler_table([{"set": "sim"}]) == []
