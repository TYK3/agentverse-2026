"""RESCUE-RUNNER-TEST2: tools/run_chain.py chain logic on synthetic legs, exit codes, one real leg."""

import json

import pytest

from tools import run_chain as rr


def verdict(fail=()):
    names = ["descended", "slab dropped", "reached"]
    steps = {n: {"ok": n not in fail, "t": None, "detail": f"d-{n}"} for n in names}
    return {"steps": steps, "passed": [n for n in names if n not in fail], "failed": list(fail)}


def leg(t_end, reached=True):
    return [{"t": 0.0, "kind": "level", "level": "L1"},
            {"t": 1.5, "kind": "plan", "status": "explore"},
            {"t": t_end, "kind": "summary", "reached": reached}]


def test_chain_cumulative_time_and_tags():
    out = rr.chain([("B1", leg(10.0), verdict()), ("B2", leg(20.0), verdict())], seed=4)
    assert out[0] == {"t": 0.0, "kind": "meta", "seed": 4, "legs": ["B1", "B2"], "source": "tools/run_chain.py"}
    b2_plan = next(r for r in out if r.get("leg") == "B2" and r["kind"] == "plan")
    assert b2_plan["t"] == 11.5 and b2_plan["leg_t"] == 1.5
    legs = [r for r in out if r["kind"] == "leg"]
    assert [(x["floor"], x["casualty"], x["t"], x["reached"]) for x in legs] == \
        [("B1", "c1", 10.0, True), ("B2", "c2", 30.0, True)]
    assert not any(r["kind"] == "summary" for r in out[:-1])         # leg summaries renamed
    assert sum(r["kind"] == "leg_summary" for r in out) == 2
    ts = [r["t"] for r in out]
    assert ts == sorted(ts)


def test_chain_steps_and_summary_pass():
    out = rr.chain([("B1", leg(10.0), verdict()), ("B3", leg(5.0), verdict())])
    steps = [r for r in out if r["kind"] == "step"]
    assert [s["name"] for s in steps][:2] == ["B1: descended", "B1: slab dropped"]
    assert len(steps) == 6 and all(s["ok"] for s in steps)
    assert out[-1] == {"t": 15.0, "kind": "summary", "legs": 2, "checks": 6, "passed": 6, "failed": []}


def test_chain_failed_leg():
    out = rr.chain([("B1", leg(10.0, reached=False), verdict(fail=("slab dropped", "reached")))])
    assert out[-1]["failed"] == ["B1: slab dropped", "B1: reached"] and out[-1]["passed"] == 1
    assert next(r for r in out if r["kind"] == "leg")["reached"] is False


def test_leg_records_drop_verdict(tmp_path):
    p = tmp_path / "b1-0.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in [*leg(3.0), {"t": 3.0, "kind": "verdict"}]) + "\n")
    assert [r["kind"] for r in rr.leg_records(p)] == ["level", "plan", "summary"]


def test_main_exit_codes(tmp_path, monkeypatch, capsys):
    seen = {}

    def fake(seed, floors, max_t, verbose):
        seen.update(seed=seed, floors=floors)
        return rr.chain([(f, leg(1.0), verdict()) for f in floors], seed)
    monkeypatch.setattr(rr, "run", fake)
    out = tmp_path / "r.jsonl"
    assert rr.main(["--seed", "2", "--floors", "B2,B3", "--out", str(out)]) == 0
    assert seen == {"seed": 2, "floors": ["B2", "B3"]}
    assert "6/6 checks passed over 2 legs" in capsys.readouterr().out
    assert json.loads(out.read_text().splitlines()[-1])["passed"] == 6
    monkeypatch.setattr(rr, "run", lambda *a: rr.chain([("B1", leg(1.0), verdict(fail=("reached",)))]))
    assert rr.main(["--out", str(out)]) == 1
    assert "FAIL B1: reached: d-reached" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="unknown floor"):
        rr.main(["--floors", "B1,B9", "--out", str(out)])


def test_real_b2_leg(tmp_path):
    pytest.importorskip("mujoco")
    records = rr.run(seed=0, floors=["B2"])
    assert records[-1]["checks"] == 9 and records[-1]["failed"] == [], records[-1]
    assert any(r["kind"] == "shift" and r["leg"] == "B2" for r in records)
    assert next(r for r in records if r["kind"] == "leg")["reached"] is True
