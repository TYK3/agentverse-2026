"""Scout evidence precedes actual supply placement in a real offline bus recording."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def survivor_observed(row):
    if row['topic'] != 'map/casualties':
        return False
    return any(c.get('id') and len(c.get('pos', [])) == 3
               and 0 < c.get('confidence', 0) <= 1 and c.get('clues')
               for c in row['data'])


def supply_placed(row):
    if row['topic'] != 'log/decision':
        return False
    data = row['data']
    return (data.get('model') == 'sim' and data.get('physics') == 'mujoco'
            and data.get('outcome') == 'done'
            and ', place_supply ' in data.get('perception', '')
            and data.get('reason', '').startswith('placed '))


def assert_find_before_delivery(rows):
    finds = [i for i, row in enumerate(rows) if survivor_observed(row)]
    assert finds, 'missing scout find: no survivor position with confidence and clues'
    deliveries = [i for i, row in enumerate(rows) if supply_placed(row)]
    assert deliveries, 'missing delivery: no completed physical place_supply decision'
    for index in deliveries:
        assert finds[0] < index and rows[finds[0]]['t'] <= rows[index]['t'], (
            f'out-of-order delivery at {rows[index]["t"]} s: '
            'scout must locate a survivor before any completed supply placement'
        )


@pytest.fixture(scope='module')
def real_rows(tmp_path_factory):
    # Dependency-based only: no opt-in flag and no fabricated or cached run.
    pytest.importorskip('mujoco', reason='the real offline runner requires root requirements')
    path = tmp_path_factory.mktemp('scout-find') / 'real.jsonl'
    code = (
        'import asyncio,sys; from tools.demo60 import run_once; '
        'asyncio.run(run_once(7, open(sys.argv[1], "w", encoding="utf-8"), '
        'auto_approve=True, duration=60))'
    )
    env = dict(os.environ, GEMINI_MODE='off', SIM_SCENE='backup')
    env.pop('SIM_RECORD', None)
    if sys.platform.startswith('linux'):
        # Pin the off-screen camera backend, even when the test host has DISPLAY.
        env['MUJOCO_GL'] = 'egl'
    result = subprocess.run([sys.executable, '-c', code, str(path)], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=180, check=False)
    assert result.returncode == 0, f'real runner failed: {result.stderr[-2000:]}'
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def test_real_scout_finds_survivor_before_any_supply_delivery(real_rows):
    assert_find_before_delivery(real_rows)


def test_missing_find_has_a_clear_failure(real_rows):
    without_find = [row for row in real_rows if not survivor_observed(row)]
    with pytest.raises(AssertionError, match='missing scout find'):
        assert_find_before_delivery(without_find)


def test_early_delivery_has_a_clear_failure(real_rows):
    placement = next(row for row in real_rows if supply_placed(row))
    with pytest.raises(AssertionError, match='out-of-order delivery'):
        assert_find_before_delivery([dict(placement, t=0), *real_rows])
