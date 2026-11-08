"""Ordering at the real JSONL writer boundary, including failed short runs."""

import copy
import json
import math
from itertools import pairwise
from pathlib import Path

import pytest

from tools import run_b2


def assert_event_order(rows):
    assert rows and rows[0]['kind'] == 'level', 'initial level must be the first event'
    kinds = [r['kind'] for r in rows]
    assert kinds.count('summary') == kinds.count('verdict') == 1, 'one summary and verdict required'
    assert kinds[-2:] == ['summary', 'verdict'], 'summary then verdict must finish the log'
    assert rows[-2]['t'] == rows[-1]['t'], 'final summary/verdict timestamps differ'
    shifts = [i for i, kind in enumerate(kinds) if kind == 'shift']
    mapped = [i for i, kind in enumerate(kinds) if kind == 'mapped']
    assert len(shifts) <= 1, 'more than one shift'
    assert len(mapped) <= 1, 'more than one mapped recheck'
    if mapped:
        assert shifts and shifts[0] < mapped[0], 'mapped recheck must follow a shift'
        assert rows[shifts[0]]['t'] < rows[mapped[0]]['t'], 'mapped recheck needs a later sensor tick'
    times = [row['t'] for row in rows]
    assert all(type(t) in (int, float) and math.isfinite(t) and t >= 0 for t in times), 'invalid time'
    assert all(a <= b for a, b in pairwise(times)), 'event time goes backwards'
    # A run may time out before a shift, or after shifting but before observing it.
    # Therefore a mapped event requires a shift, not the converse.


@pytest.mark.parametrize('floor', ['B2', 'B3'])
def test_short_real_log_event_order(tmp_path, monkeypatch, floor):
    pytest.importorskip('mujoco')
    monkeypatch.setenv('GEMINI_MODE', 'off')
    _, path = run_b2.run(seed=0, max_t=0.2, out_dir=tmp_path, floor=floor)
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    assert_event_order(rows)
    assert {'level', 'pose', 'plan', 'summary', 'verdict'} <= {r['kind'] for r in rows}
    assert not any(r['kind'] in ('shift', 'mapped') for r in rows)


@pytest.mark.parametrize('floor', ['B2', 'B3'])
def test_complete_real_event_headers(floor):
    assert_event_order(RECORDED_HEADERS[floor])


@pytest.mark.parametrize('mutation', ['no_initial_level', 'backwards_time', 'early_verdict',
                                      'mapped_before_shift', 'mapped_without_shift',
                                      'duplicate_shift', 'duplicate_mapped', 'terminal_time'])
def test_corrupt_order_has_a_named_failure(mutation):
    rows = copy.deepcopy(RECORDED_HEADERS['B2'])
    shift = next(i for i, r in enumerate(rows) if r['kind'] == 'shift')
    mapped = next(i for i, r in enumerate(rows) if r['kind'] == 'mapped')
    if mutation == 'no_initial_level':
        rows = [r for r in rows if r['kind'] != 'level']
        message = 'initial level'
    elif mutation == 'backwards_time':
        rows[2]['t'] = rows[1]['t'] - 0.1
        message = 'time goes backwards'
    elif mutation == 'early_verdict':
        rows.insert(1, rows.pop())
        message = 'summary then verdict'
    elif mutation == 'mapped_before_shift':
        rows[shift], rows[mapped] = rows[mapped], rows[shift]
        message = 'mapped recheck must follow'
    elif mutation == 'mapped_without_shift':
        rows.pop(shift)
        message = 'mapped recheck must follow'
    elif mutation == 'duplicate_shift':
        rows.insert(shift, copy.deepcopy(rows[shift]))
        message = 'more than one shift'
    elif mutation == 'duplicate_mapped':
        rows.insert(mapped, copy.deepcopy(rows[mapped]))
        message = 'more than one mapped'
    else:
        rows[-1]['t'] += 0.1
        message = 'timestamps differ'
    with pytest.raises(AssertionError, match=message):
        assert_event_order(rows)


# Exact kind/time/level projections from complete real seed-0 B2/B3 logs,
# tools/run_b2.py --seed 0 --floor B2/B3, main 8411ab5. No events are synthesised.
# Pose/plan rows are omitted here; live-prefix tests include every emitted row.
RECORDED_HEADERS = json.loads(r'''
{
  "B2": [
    {
      "t": 0.0,
      "kind": "level",
      "level": "L1"
    },
    {
      "t": 21.6,
      "kind": "level",
      "level": "ground"
    },
    {
      "t": 80.1,
      "kind": "level",
      "level": "B1"
    },
    {
      "t": 155.3,
      "kind": "level",
      "level": "B2"
    },
    {
      "t": 173.6,
      "kind": "shift",
      "level": "B2"
    },
    {
      "t": 173.7,
      "kind": "mapped"
    },
    {
      "t": 179.3,
      "kind": "summary"
    },
    {
      "t": 179.3,
      "kind": "verdict"
    }
  ],
  "B3": [
    {
      "t": 0.0,
      "kind": "level",
      "level": "L1"
    },
    {
      "t": 21.6,
      "kind": "level",
      "level": "ground"
    },
    {
      "t": 65.9,
      "kind": "level",
      "level": "B1"
    },
    {
      "t": 142.9,
      "kind": "level",
      "level": "B2"
    },
    {
      "t": 217.0,
      "kind": "level",
      "level": "B3"
    },
    {
      "t": 225.8,
      "kind": "shift",
      "level": "B3"
    },
    {
      "t": 226.0,
      "kind": "mapped"
    },
    {
      "t": 230.9,
      "kind": "summary"
    },
    {
      "t": 230.9,
      "kind": "verdict"
    }
  ]
}
''')
