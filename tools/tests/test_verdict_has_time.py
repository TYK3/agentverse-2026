"""Verdict timestamps are real simulation time, not wall time or payload guesses."""

import copy
import json
import math
from pathlib import Path

import pytest

from tools import run_b2


def assert_verdict_time(rows):
    verdicts = [row for row in rows if row['kind'] == 'verdict']
    assert len(verdicts) == 1, 'expected one real verdict record'
    verdict = verdicts[0]
    assert 't' in verdict, 'verdict missing simulation time t'
    time = verdict['t']
    assert isinstance(time, (int, float)) and not isinstance(time, bool), 'verdict time must be numeric'
    assert math.isfinite(time), 'verdict time must be finite'
    assert time >= 0, 'verdict time must be non-negative'
    summary = next(row for row in rows if row['kind'] == 'summary')
    assert time == summary['t'], 'verdict time differs from the final summary time'
    assert time >= max(row['t'] for row in rows), 'verdict predates a logged event'


@pytest.mark.parametrize('key', [f'{floor}-{duration}' for floor in ('B1', 'B2', 'B3') for duration in (.2, 2.2)])
def test_recorded_verdict_has_real_end_time(key):
    assert_verdict_time(RECORDED[key])


@pytest.mark.parametrize('floor', ['B1', 'B2', 'B3'])
@pytest.mark.parametrize('duration', [.2, 2.2])
def test_live_verdict_carries_elapsed_simulation_time(tmp_path, monkeypatch, floor, duration):
    pytest.importorskip('mujoco')
    monkeypatch.setenv('GEMINI_MODE', 'off')
    _, path = run_b2.run(seed=0, max_t=duration, out_dir=tmp_path, floor=floor)
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    assert_verdict_time(rows)
    verdict = next(row for row in rows if row['kind'] == 'verdict')
    # The bounded run ends at its requested limit (within one 0.1 s tick).
    assert duration <= verdict['t'] <= duration + 0.1


@pytest.mark.parametrize('mutation', ['missing', 'bool', 'string', 'nan', 'inf', 'negative', 'early', 'late'])
def test_bad_verdict_time_is_rejected(mutation):
    rows = copy.deepcopy(RECORDED['B2-2.2'])
    verdict = rows[-1]
    assert verdict['kind'] == 'verdict'
    if mutation == 'missing':
        del verdict['t']
        message = 'missing simulation time'
    elif mutation in ('bool', 'string'):
        verdict['t'] = True if mutation == 'bool' else '2.2'
        message = 'must be numeric'
    elif mutation in ('nan', 'inf'):
        verdict['t'] = float(mutation)
        message = 'must be finite'
    elif mutation == 'negative':
        verdict['t'] = -0.1
        message = 'must be non-negative'
    else:
        verdict['t'] += -0.1 if mutation == 'early' else 0.1
        message = 'differs from the final summary'
    with pytest.raises(AssertionError, match=message):
        assert_verdict_time(rows)


# Actual kind/t projections from six temporary seed-0 logs on main f56f34e.
# Failed short-run mission verdicts still carry their genuine end time.
RECORDED = {'B1-0.2': [{'kind': 'summary', 't': 0.2}, {'kind': 'verdict', 't': 0.2}],
 'B1-2.2': [{'kind': 'summary', 't': 2.2}, {'kind': 'verdict', 't': 2.2}],
 'B2-0.2': [{'kind': 'summary', 't': 0.2}, {'kind': 'verdict', 't': 0.2}],
 'B2-2.2': [{'kind': 'summary', 't': 2.2}, {'kind': 'verdict', 't': 2.2}],
 'B3-0.2': [{'kind': 'summary', 't': 0.2}, {'kind': 'verdict', 't': 0.2}],
 'B3-2.2': [{'kind': 'summary', 't': 2.2}, {'kind': 'verdict', 't': 2.2}]}
