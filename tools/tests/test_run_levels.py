"""RESCUE-RUNNER-TEST: tools/run_levels.py verdict from synthetic logs, exit codes, one real run."""

import json

import pytest

from tools import run_levels as rl


def good_log():
    recs = [{"t": 0.0, "kind": "meta", "seed": 0, "legs": list(rl.LEGS)}]
    recs += [{"t": float(i), "kind": "level", "level": lv} for i, lv in enumerate(rl.ORDER)]
    recs += [{"t": 88.7, "kind": "leg", "floor": "B1", "casualty": "c1", "reached": True},
             {"t": 175.5, "kind": "leg", "floor": "B2", "casualty": "c2", "reached": True},
             {"t": 231.6, "kind": "leg", "floor": "B3", "casualty": "c3", "reached": True},
             {"t": 231.6, "kind": "summary", "max_jump": 0.0313, "responder_route": "ok"}]
    return recs


def failed(recs):
    return rl.evaluate(recs)["failed"]


def test_all_steps_pass():
    v = rl.evaluate(good_log())
    assert v["failed"] == [] and [n for n, _, _ in v["steps"]] == rl.steps()


@pytest.mark.parametrize("floor,cas", [("B1", "c1"), ("B2", "c2"), ("B3", "c3")])
def test_each_casualty_not_reached(floor, cas):
    recs = [dict(r, reached=False) if r.get("floor") == floor else r for r in good_log()]
    assert failed(recs) == [f"reached {cas} on {floor}"]


def test_missing_leg_is_a_failure():
    recs = [r for r in good_log() if r.get("floor") != "B3"]
    v = rl.evaluate(recs)
    assert v["failed"] == ["reached c3 on B3"]
    assert {n: d for n, _, d in v["steps"]}["reached c3 on B3"] == "leg not run"


def test_jump_over_limit_and_missing_summary():
    recs = [dict(r, max_jump=rl.MAX_JUMP + 0.001) if r["kind"] == "summary" else r for r in good_log()]
    assert failed(recs) == ["no teleport"]
    at_limit = [dict(r, max_jump=rl.MAX_JUMP) if r["kind"] == "summary" else r for r in good_log()]
    assert failed(at_limit) == []
    no_summary = [r for r in good_log() if r["kind"] != "summary"]
    assert set(failed(no_summary)) == {"no teleport", "route over the scouted map from L1 to B3"}


@pytest.mark.parametrize("levels", [["L1", "ground", "B2", "B1", "B3"], ["L1", "ground", "B1", "B2"],
                                    ["L1", "ground", "B1", "ground", "B1", "B2", "B3"]])
def test_wrong_floor_order(levels):
    recs = [r for r in good_log() if r["kind"] != "level"]
    recs += [{"t": 1.0, "kind": "level", "level": lv} for lv in levels]
    assert failed(recs) == ["levels in order L1 > ground > B1 > B2 > B3"]


def test_no_responder_route():
    recs = [dict(r, responder_route="explore") if r["kind"] == "summary" else r for r in good_log()]
    assert failed(recs) == ["route over the scouted map from L1 to B3"]


def test_main_exit_codes_and_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rl, "run", lambda seed, max_t, verbose: good_log())
    out = tmp_path / "levels.jsonl"
    assert rl.main(["--out", str(out)]) == 0
    assert "6/6 steps passed" in capsys.readouterr().out
    assert [json.loads(x) for x in out.read_text().splitlines()] == good_log()
    bad = [dict(r, reached=False) if r.get("floor") == "B2" else r for r in good_log()]
    monkeypatch.setattr(rl, "run", lambda seed, max_t, verbose: bad)
    assert rl.main(["--out", str(out)]) == 1
    assert "failed: reached c2 on B2" in capsys.readouterr().out


def test_real_chained_run(tmp_path):
    pytest.importorskip("mujoco")
    recs = rl.run(seed=0)
    v = rl.evaluate(recs)
    assert v["failed"] == [], v["steps"]
    legs = [r for r in recs if r["kind"] == "leg"]
    assert [r["floor"] for r in legs] == list(rl.LEGS)
    assert legs[0]["t"] < legs[1]["t"] < legs[2]["t"]
    assert sum(r["kind"] == "plan" for r in recs) > 50
    assert [r for r in recs if r["kind"] == "step"] and all(r["ok"] for r in recs if r["kind"] == "step")
