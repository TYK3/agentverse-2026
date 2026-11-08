"""tools/seed_sweep.py with a mocked subprocess (no real rescue runs)."""

import subprocess
import types

from tools import seed_sweep as ss


def repo(tmp_path, script=True):
    if script:
        (tmp_path / "tools").mkdir()
        (tmp_path / "tools" / "run_rescue.py").write_text("")
    return tmp_path


def fake(outcomes, calls):
    def runner(cmd, **kw):
        seed = int(cmd[cmd.index("--seed") + 1])
        calls.append((cmd, kw))
        o = outcomes[seed]
        if o == "timeout":
            raise subprocess.TimeoutExpired(cmd, kw["timeout"], output=b"scout exploring")
        return types.SimpleNamespace(returncode=o[0], stdout=o[1], stderr="")
    return runner


def test_success_failure_timeout(tmp_path):
    calls = []
    run = fake({0: (0, "15/15 steps passed\n"), 1: (1, "14/15 steps passed; failed: deliver\n"),
                2: "timeout"}, calls)
    results, rate = ss.sweep([0, 1, 2], timeout=5, root=repo(tmp_path), runner=run)
    assert [r["status"] for r in results] == ["pass", "fail", "timeout"]
    assert rate == 1 / 3
    assert results[1]["reason"] == "14/15 steps passed; failed: deliver"
    assert "no result after 5 s" in results[2]["reason"]
    cmd, kw = calls[0]
    assert "--auto-approve" in cmd and kw["env"]["GEMINI_MODE"] == "off" and kw["timeout"] == 5
    md = ss.section(results, rate)
    assert "Success rate: 1/3 = 33%" in md and "| 1 | FAIL |" in md


def test_missing_script_skips_every_seed(tmp_path):
    def boom(*a, **k):
        raise AssertionError("must not run")
    results, rate = ss.sweep([0, 1], root=repo(tmp_path, script=False), runner=boom)
    assert {r["status"] for r in results} == {"skipped"} and rate is None
    assert "n/a, all 2 seeds skipped" in ss.section(results, rate)


def test_main_exit_codes(tmp_path):
    root = repo(tmp_path)
    ok = fake({0: (0, "ok"), 1: (0, "ok")}, [])
    assert ss.main(["--seeds", "0-1", "--output", "r.md"], root=root, runner=ok) == 0
    bad = fake({0: (0, "ok"), 1: (1, "")}, [])
    assert ss.main(["--seeds", "0,1", "--output", "r.md"], root=root, runner=bad) == 1
    assert ss.main(["--output", "s.md"], root=repo(tmp_path / "x", script=False)) == 0


def test_section_replaced_or_appended(tmp_path):
    path = tmp_path / "runs" / "full_test.md"
    ss.write_section(path, ss.section([], None))
    assert path.read_text().count(ss.BEGIN) == 1
    path.write_text("# Full test run\n\nkeep me\n")
    ss.write_section(path, f"{ss.BEGIN}\nold\n{ss.END}\n")
    ss.write_section(path, ss.BEGIN + "\nnew\n" + ss.END + "\n")
    text = path.read_text()
    assert text.startswith("# Full test run") and "keep me" in text
    assert text.count(ss.BEGIN) == 1 and "new" in text


def test_seeds_parse():
    assert ss.seeds_from("0-4") == [0, 1, 2, 3, 4]
    assert ss.seeds_from("3,7") == [3, 7]
