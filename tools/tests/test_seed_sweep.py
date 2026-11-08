"""tools/seed_sweep.py with a mocked subprocess (no real rescue runs)."""

import json
import subprocess
import sys
import types

import pytest

from tools import seed_sweep as ss
from tools import seed_sweep_b1 as b1


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


@pytest.mark.parametrize(('returncode', 'checks', 'expected'), [
    (0, [True] * 4, 'pass'),
    (1, [True] * 4, 'fail'),
    (0, [True, True, True, False], 'fail'),
    (0, [True] * 3, 'fail'),
    (0, None, 'fail'),
])
def test_b1_requires_child_exit_and_complete_evidence(tmp_path, monkeypatch, returncode, checks, expected):
    monkeypatch.setenv('GEMINI_MODE', 'live')
    path = tmp_path / 'b1-7.json'
    path.write_text('{"stale": true}')

    def runner(command, **kwargs):
        assert not path.exists(), 'previous successful evidence must be cleared'
        assert command[0] == sys.executable
        assert command[command.index('--seed') + 1] == '7'
        assert command[command.index('--max-t') + 1] == '12'
        assert '--child' in command
        assert kwargs['env']['GEMINI_MODE'] == 'off'
        assert kwargs['timeout'] == 3
        assert kwargs['cwd'] == b1.ROOT
        assert kwargs['capture_output'] and kwargs['text'] and not kwargs['check']
        if checks is not None:
            path.write_text(json.dumps({'t': 8.5, 'checks': {str(i): ok for i, ok in enumerate(checks)}}))
        return types.SimpleNamespace(returncode=returncode, stdout='result\n', stderr='')

    monkeypatch.setattr(b1.subprocess, 'run', runner)
    row = b1.run_seed(7, timeout=3, max_t=12, out_dir=tmp_path)
    assert row['status'] == expected
    assert row['seed'] == 7 and row['seconds'] >= 0
    assert row['sim_seconds'] == (8.5 if checks is not None else None)
    assert row['reason'] == 'result'
    assert (tmp_path / 'b1-7.log').read_text() == 'result\n'


def test_b1_timeout_keeps_partial_output_and_discards_stale_result(tmp_path, monkeypatch):
    path = tmp_path / 'b1-0.json'
    path.write_text('{"checks": {"old": true}}')

    def timeout(command, **kwargs):
        assert not path.exists()
        raise subprocess.TimeoutExpired(command, kwargs['timeout'], output=b'partial\n', stderr=b'error')

    monkeypatch.setattr(b1.subprocess, 'run', timeout)
    row = b1.run_seed(0, timeout=0.01, max_t=5, out_dir=tmp_path)
    assert row['status'] == 'timeout' and row['sim_seconds'] is None
    assert row['checks'] == {} and row['reason'] == 'error'
    assert (tmp_path / 'b1-0.log').read_text() == 'partial\nerror'


@pytest.mark.parametrize('statuses', [('pass', 'pass'), ('pass', 'fail'), ('pass', 'timeout')])
def test_b1_main_reports_every_seed_and_correct_exit(tmp_path, monkeypatch, capsys, statuses):
    monkeypatch.setenv('GEMINI_MODE', 'live')
    calls = []

    def run(seed, timeout, max_t, out_dir):
        calls.append((seed, timeout, max_t, out_dir))
        return {'seed': seed, 'status': statuses[seed], 'seconds': 0.1, 'sim_seconds': 2,
                'reason': 'mock result', 'checks': {}}

    monkeypatch.setattr(b1, 'run_seed', run)
    out = tmp_path / 'reports'
    code = b1.main(['--seeds', '0-1', '--timeout', '3', '--max-t', '4', '--out-dir', str(out)])
    passed = statuses.count('pass')
    assert code == (0 if passed == 2 else 1)
    assert calls == [(0, 3, 4, out), (1, 3, 4, out)]
    report = json.loads((out / 'seed_sweep_b1.json').read_text())
    assert report['passed'] == passed and report['total'] == 2
    assert [row['status'] for row in report['results']] == list(statuses)
    text = (out / 'seed_sweep_b1.md').read_text()
    assert f'B1: {passed}/2 passed' in text
    assert f'| 1 | {statuses[1].upper()} |' in text
    assert f'seed 1: {statuses[1].upper()}' in capsys.readouterr().out


@pytest.mark.parametrize('seeds', ['', '2-1', '0,0', '-1', 'x'])
def test_b1_invalid_seeds_never_launch_a_child(tmp_path, monkeypatch, seeds):
    def unexpected(*args, **kwargs):
        pytest.fail('invalid arguments must not launch a child')

    monkeypatch.setattr(b1, 'run_seed', unexpected)
    with pytest.raises(SystemExit) as exc:
        b1.main(['--seeds', seeds, '--out-dir', str(tmp_path)])
    assert exc.value.code == 2


@pytest.mark.parametrize('value', ['0', '-1', 'inf', 'nan'])
@pytest.mark.parametrize('option', ['--timeout', '--max-t'])
def test_b1_rejects_invalid_time_limits(tmp_path, option, value):
    with pytest.raises(SystemExit) as exc:
        b1.main([option, value, '--out-dir', str(tmp_path)])
    assert exc.value.code == 2


@pytest.mark.parametrize(('change', 'expected'), [
    ({}, 0), ({'reached': False}, 1), ({'levels': ['L1', 'B1']}, 1),
    ({'max_jump': 0.035}, 1), ({'responder_route': 'blocked'}, 1), ({'route_k': None}, 1),
])
def test_b1_child_binds_real_world_seed_and_checks_result(tmp_path, monkeypatch, change, expected):
    seeds = []
    python_seeds = []
    monkeypatch.setattr(b1.random, 'seed', python_seeds.append)
    world_seeds = []
    np = types.SimpleNamespace(random=types.SimpleNamespace(seed=seeds.append))
    sim = types.ModuleType('sim')
    levels = types.ModuleType('sim.levels')

    def world(*, seed, render):
        assert render is False
        world_seeds.append(seed)

    def descent(*, max_t, floor):
        assert max_t == 10 and floor == 'B1'
        sim.demo_descent.LevelWorld(render=False)
        return {'reached': True, 'levels': ['L1', 'ground', 'B1'], 'max_jump': 0.031,
                'responder_route': 'ok', 'route_k': (12, -12), 't': 8,
                'map': {}, 'log': [], 'trail': [], 'trace': [], **change}

    levels.LevelWorld = world
    sim.demo_descent = types.SimpleNamespace(run=descent)
    monkeypatch.setitem(sys.modules, 'numpy', np)
    monkeypatch.setitem(sys.modules, 'sim', sim)
    monkeypatch.setitem(sys.modules, 'sim.levels', levels)
    assert b1.child(23, max_t=10, out_dir=tmp_path) == expected
    assert seeds == [23] and python_seeds == [23] and world_seeds == [23]
    result = json.loads((tmp_path / 'b1-23.json').read_text())
    assert result['seed'] == 23 and len(result['checks']) == 4
    assert all(result['checks'].values()) is (expected == 0)
    assert not {'map', 'log', 'trail', 'trace'} & result.keys()
