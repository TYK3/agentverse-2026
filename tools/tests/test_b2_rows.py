"""B2-ROWS (ref b2): descent rows in full_test and the seed sweep over the B2 descent (mocked)."""

import sys
import types

import pytest

from tools import full_test as ft
from tools import seed_sweep as ss


def test_descent_command_and_markers():
    cmd = ss.command(3, "B2")
    assert cmd[cmd.index("--descent-child") + 1] == "B2" and cmd[-1] == "3"
    assert ss.command(3)[1] == ss.RESCUE
    assert ss.markers("B2") == ("<!-- SEED-SWEEP-B2:BEGIN -->", "<!-- SEED-SWEEP-B2:END -->")
    assert ss.markers() == (ss.BEGIN, ss.END)


def test_b2_sweep_mocked(tmp_path):
    (tmp_path / "sim").mkdir()
    (tmp_path / "sim" / "demo_descent.py").write_text("")
    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)
        seed = int(cmd[-1])
        return types.SimpleNamespace(returncode=0 if seed else 1,
                                     stdout=f"reached={bool(seed)} t=176.4 levels=L1>ground>B1>B2", stderr="")
    results, rate = ss.sweep([0, 1, 2], 5, tmp_path, runner, floor="B2")
    assert [r["status"] for r in results] == ["fail", "pass", "pass"] and rate == 2 / 3
    assert all("--descent-child" in c for c in calls)
    md = ss.section(results, rate, "B2")
    assert md.startswith("<!-- SEED-SWEEP-B2:BEGIN -->") and "L1 -> B2 descent" in md
    assert "unscripted" in md and "2/3 = 67%" in md


def test_b2_sweep_skips_without_descent(tmp_path):
    results, rate = ss.sweep([0], root=tmp_path, floor="B2",
                             runner=lambda *a, **k: pytest.fail("must not run"))
    assert results[0]["status"] == "skipped" and "demo_descent" in results[0]["reason"] and rate is None


def test_b2_and_rescue_sections_are_separate(tmp_path):
    path = tmp_path / "full_test.md"
    ss.write_section(path, ss.section([], None))
    ss.write_section(path, ss.section([], None, "B2"), "B2")
    ss.write_section(path, ss.section([], None, "B2"), "B2")
    text = path.read_text()
    assert text.count(ss.BEGIN) == 1 and text.count("SEED-SWEEP-B2:BEGIN") == 1


def test_descent_child_exit_code(monkeypatch, capsys):
    fake = types.ModuleType("sim.demo_descent")
    outcome = {"reached": True, "t": 176.4, "levels": ["L1", "ground", "B1", "B2"],
               "max_jump": 0.031, "responder_route": "ok"}
    fake.run = lambda floor: dict(outcome)
    monkeypatch.setitem(sys.modules, "sim.demo_descent", fake)
    assert ss.descent_child("B2", 0) == 0
    assert "levels=L1>ground>B1>B2" in capsys.readouterr().out
    outcome["levels"] = ["L1", "ground", "B1"]
    assert ss.descent_child("B2", 0) == 1             # stopped on B1: not a B2 pass
    outcome.update(levels=["L1", "ground", "B1", "B2"], reached=False)
    assert ss.descent_child("B2", 0) == 1


def test_full_test_plans_b2_rows(tmp_path):
    (tmp_path / "sim").mkdir()
    (tmp_path / "sim" / "demo_descent.py").write_text("")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "seed_sweep.py").write_text("")
    jobs = {name: (cmd, t) for name, cmd, t in ft.plan(tmp_path, [], 1, 100)}
    cmd, t = jobs["descent B2 (strict)"]
    assert cmd[1:] == ["tools/seed_sweep.py", "--descent-child", "B2", "--seed", "0"] and t == 100
    cmd, t = jobs["seed sweep B2 (seeds 0-4)"]
    assert "--floor" in cmd and t == 500
    assert all(n not in [j[0] for j in ft.plan(tmp_path, [], 1, 100, demos=False)] for n in jobs
               if "B2" in n)
    missing = {n: why for n, c, why in ft.plan(tmp_path / "x", [], 1, 100)}
    assert "not on this checkout" in missing["descent B2 (strict)"]


def test_full_test_keeps_sweep_sections(tmp_path):
    out = tmp_path / "full_test.md"
    out.write_text("# old\n\n" + ss.section([], None, "B2") + "\n" + ss.section([], None))
    kept = ft.kept_sections(out)
    assert "SEED-SWEEP-B2:BEGIN" in kept and ss.BEGIN in kept and "# old" not in kept
    assert ft.kept_sections(tmp_path / "missing.md") == ""
