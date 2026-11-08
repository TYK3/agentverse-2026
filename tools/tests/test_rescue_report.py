"""tools/rescue_report.py on synthetic run_levels and run_b2 logs, plus a real run_levels log."""

import json

import pytest

from tools import rescue_report as rr


def levels_log(ok=True):
    recs = [{"t": 0.0, "kind": "meta", "seed": 3, "legs": ["B1", "B2"], "source": "tools/run_levels.py"},
            {"t": 0.0, "kind": "level", "level": "L1"}, {"t": 20.0, "kind": "level", "level": "B1"},
            {"t": 1.0, "kind": "plan", "leg": "B1", "why": "explore"},
            {"t": 2.0, "kind": "plan", "leg": "B1", "why": "probe"},
            {"t": 30.0, "kind": "leg", "floor": "B1", "casualty": "c1", "reached": True},
            {"t": 31.0, "kind": "plan", "leg": "B2", "why": "route"},
            {"t": 70.0, "kind": "leg", "floor": "B2", "casualty": "c2", "reached": ok,
             **({} if ok else {"stuck": "no | path"})},
            {"t": 70.0, "kind": "summary", "max_jump": 0.03, "responder_route": "ok"},
            {"t": 70.0, "kind": "step", "name": "reached c1 on B1", "ok": True, "detail": "t=30.0"},
            {"t": 70.0, "kind": "step", "name": "reached c2 on B2", "ok": ok, "detail": "t=70.0"}]
    return recs


def b2_log():
    return [{"t": 0.0, "kind": "level", "level": "L1"},
            {"t": 150.0, "kind": "shift", "xy": [1.1, 0.9], "level": "B2"},
            {"t": 160.0, "kind": "summary", "reached": True},
            {"t": 160.0, "kind": "verdict", "passed": ["a"], "failed": ["b"], "steps": {
                "a": {"ok": True, "t": 150.0, "detail": "slab"},
                "b": {"ok": False, "t": None, "detail": "x"}}}]


def test_levels_report_pass():
    md = rr.report(levels_log(), "levels-3")
    assert md.startswith("# Rescue report: levels-3")
    assert "**PASS**: 2/2 checks passed" in md and "seed 3" in md and "70.0 s of sim time" in md
    assert "3 planner decisions" in md
    assert "| ok | reached c1 on B1 | - | t=30.0 |" in md
    assert "L1 (0.0 s) > B1 (20.0 s)" in md
    assert "| B1 | c1 | yes | 0.0 s | 30.0 s | 30.0 s | explore 1, probe 1 |" in md
    assert "| B2 | c2 | yes | 30.0 s | 70.0 s | 40.0 s | route 1 |" in md
    assert "| responder_route | \"ok\" |" in md and "World change" not in md


def test_levels_report_fail_and_pipe_escaped():
    md = rr.report(levels_log(ok=False))
    assert "**FAIL**: 1/2 checks passed" in md and "| FAIL | reached c2 on B2 |" in md
    assert "no: no / path" in md                       # a | in the reason never breaks the table


def test_b2_verdict_and_shift():
    md = rr.report(b2_log(), "b2-0")
    assert "**FAIL**: 1/2 checks passed" in md and "Source tools/run_b2.py" in md
    assert "| ok | a | 150.0 s | slab |" in md and "| FAIL | b | - | x |" in md
    assert "Slab dropped at 150.0 s on B2 at [1.1, 0.9]." in md and "Casualty legs" not in md


def test_no_checks():
    assert "no checks in this log" in rr.report([{"t": 0.0, "kind": "level", "level": "L1"}])


@pytest.mark.parametrize("recs,code", [(levels_log(), 0), (levels_log(ok=False), 1),
                                       ([{"t": 0.0, "kind": "level", "level": "L1"}], 2)])
def test_main_exit_codes_and_default_path(tmp_path, recs, code, capsys):
    log = tmp_path / "levels-3.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in recs) + "\n")
    assert rr.main([str(log)]) == code
    assert (tmp_path / "levels-3.md").read_text().startswith("# Rescue report: levels-3")
    assert rr.main([str(log), "--out", "-"]) == code
    assert "# Rescue report" in capsys.readouterr().out


def test_real_run_levels_log(tmp_path):
    pytest.importorskip("mujoco")
    from tools import run_levels

    log = tmp_path / "levels-0.jsonl"
    assert run_levels.main(["--out", str(log)]) == 0
    md = rr.report(rr.load(log), "levels-0")
    assert "**PASS**: 6/6 checks passed" in md
    assert all(f"| {f} | {c} | yes |" in md for f, c in (("B1", "c1"), ("B2", "c2"), ("B3", "c3")))
