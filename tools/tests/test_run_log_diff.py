"""tools/run_log_diff.py on synthetic logs, plus two real runs of the same seed."""

import json

import pytest

from tools import run_log_diff as rd


def log(t_shift=0.0, ok=True, extra=False, x=1.0):
    recs = [{"t": 0.0, "kind": "meta", "seed": 0, "wall": 12.3},
            {"t": 1.0 + t_shift, "kind": "plan", "target": [x, 2.0, 0.0]},
            {"t": 2.0, "kind": "pose", "pos": [0.1, 0.2, 0.0]},
            {"t": 3.0, "kind": "step", "name": "reached c1", "ok": ok, "detail": "x"}]
    return recs + ([{"t": 4.0, "kind": "plan", "target": [0, 0, 0]}] if extra else [])


def test_identical_and_wall_ignored():
    b = log()
    b[0]["wall"] = 99.0
    d = rd.diff(log(), b)
    assert d["same"] and d["records"] == (4, 4)
    assert rd.render(d).startswith("same: 4 records match")


def test_time_tolerance():
    assert not rd.diff(log(), log(t_shift=0.3))["same"]
    assert rd.diff(log(), log(t_shift=0.3), t_tol=0.5)["same"]


def test_position_tolerance_separate_from_time():
    assert not rd.diff(log(), log(x=1.01), t_tol=1.0)["same"]
    assert rd.diff(log(), log(x=1.01), pos_tol=0.02)["same"]


def test_check_change_and_first_difference():
    d = rd.diff(log(), log(ok=False))
    assert d["checks_changed"] == {"reached c1": (True, False)}
    assert d["first"]["index"] == 3
    text = rd.render(d, "run1", "run2")
    assert "check reached c1: True -> False" in text and "first difference at record 3" in text


def test_extra_record_counts_and_end_of_log():
    d = rd.diff(log(), log(extra=True))
    assert d["counts"] == {"plan": (1, 2)} and d["first"]["a"] is None
    assert "(end of log)" in rd.render(d)


def test_ignore_kind():
    b = log()
    b[2]["pos"] = [9, 9, 9]
    assert not rd.diff(log(), b)["same"]
    assert rd.diff(log(), b, ignore={"pose"})["same"]


def test_verdict_checks_and_topic_logs():
    a = [{"t": 0, "topic": "map/cells", "data": {}}, {"t": 1, "kind": "verdict", "steps": {"s": {"ok": True}}}]
    b = [{"t": 0, "topic": "map/cells", "data": {}}, {"t": 1, "kind": "verdict", "steps": {"s": {"ok": False}}}]
    d = rd.diff(a, b)
    assert d["checks_changed"] == {"s": (True, False)} and rd.kind(a[0]) == "map/cells"


def test_main_exit_codes(tmp_path, capsys):
    pa, pb = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    pa.write_text("".join(json.dumps(r) + "\n" for r in log()))
    pb.write_text("".join(json.dumps(r) + "\n" for r in log(t_shift=0.2)) + "\n")
    assert rd.main([str(pa), str(pa)]) == 0
    assert rd.main([str(pa), str(pb)]) == 1
    assert rd.main([str(pa), str(pb), "--t-tol", "0.25"]) == 0
    assert "a.jsonl" in capsys.readouterr().out


def test_real_same_seed_runs_match(tmp_path):
    pytest.importorskip("mujoco")
    from tools import run_levels

    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    run_levels.main(["--out", str(a)])
    run_levels.main(["--out", str(b)])
    assert rd.main([str(a), str(b)]) == 0
