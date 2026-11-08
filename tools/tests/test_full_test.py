"""tools/full_test.py on a throwaway repo with fake suites (no real lanes run)."""

import sys

from tools import full_test


def make_repo(tmp_path, rescue=None):
    (tmp_path / "good").mkdir()
    (tmp_path / "good" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "test_no.py").write_text("def test_no():\n    assert False\n")
    (tmp_path / "slow").mkdir()
    (tmp_path / "slow" / "test_slow.py").write_text(
        "import time\n\ndef test_slow():\n    time.sleep(30)\n")
    if rescue is not None:
        (tmp_path / "tools").mkdir()
        (tmp_path / "tools" / "run_rescue.py").write_text(rescue)
    return tmp_path


def go(tmp_path, *extra):
    argv = ["--output", "out/report.md", "--timeout", "3", "--rescue-timeout", "3", *extra]
    code = full_test.main(argv, root=tmp_path)
    return code, (tmp_path / "out" / "report.md").read_text()


def test_pass_only_gives_zero_and_table(tmp_path):
    code, md = go(make_repo(tmp_path), "--suite", "good")
    assert code == 0
    assert "| good | PASS | 1 passed |" in md
    assert "| e2e rescue | SKIPPED | tools/run_rescue.py not on this checkout |" in md


def test_failure_timeout_and_missing_are_reported(tmp_path):
    code, md = go(make_repo(tmp_path), "--suite", "good", "--suite", "bad",
                  "--suite", "slow", "--suite", "gone")
    assert code == 1
    assert "| bad | FAIL | 1 failed |" in md
    assert "| slow | TIMEOUT |" in md
    assert "| gone | SKIPPED | folder not on this checkout |" in md
    assert "## bad: fail" in md and "assert False" in md


def test_rescue_runs_with_seed_and_gemini_off(tmp_path):
    script = ("import os, sys\nprint('seed', sys.argv[sys.argv.index('--seed') + 1],"
              " os.environ['GEMINI_MODE'])\nsys.exit(0 if '--auto-approve' in sys.argv else 2)\n")
    code, md = go(make_repo(tmp_path, rescue=script), "--suite", "good", "--seed", "4")
    assert code == 0
    assert "| e2e rescue (seed 4) | PASS |" in md
    assert "seed 4 off" in md


def test_failing_rescue_fails_the_run(tmp_path):
    code, md = go(make_repo(tmp_path, rescue="import sys\nsys.exit(3)\n"), "--suite", "good")
    assert code == 1 and "| e2e rescue (seed 1) | FAIL |" in md


def test_no_rescue_flag(tmp_path):
    code, md = go(make_repo(tmp_path, rescue="import sys\nsys.exit(3)\n"),
                  "--suite", "good", "--no-rescue")
    assert code == 0 and "| e2e rescue (seed 1) | SKIPPED | --no-rescue |" in md


def test_summary_parses_pytest_line():
    assert full_test.summary("x\n==== 3 passed, 1 skipped in 0.12s ====\n") == "3 passed, 1 skipped"
    assert full_test.summary("no pytest here") == ""
    assert sys.executable
