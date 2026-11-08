"""The actual shift floor label is `level`, corroborated by real level records."""

import copy
import json
from pathlib import Path

import pytest

from tools import run_b2

FLOORS = ('B1', 'B2', 'B3')


def assert_shift_floors(rows, require_shift=False):
    summary = next(row for row in rows if row['kind'] == 'summary')
    assert summary['floor'] in FLOORS, 'invalid target floor'
    current = None
    count = 0
    for row in rows:
        if row['kind'] == 'level':
            current = row['level']
        elif row['kind'] == 'shift':
            count += 1
            assert 'level' in row, 'shift missing its level/floor name'
            assert isinstance(row['level'], str) and row['level'] in FLOORS, 'invalid shift level/floor name'
            assert row['level'] == summary['floor'], 'shift names the wrong target floor'
            assert row['level'] == current, 'shift floor disagrees with preceding level record'
    if require_shift:
        assert count > 0, 'no real shift: floor assertion must not pass vacuously'


@pytest.mark.parametrize('floor', ['B2', 'B3'])
def test_every_genuine_shift_names_its_floor(floor):
    assert_shift_floors(RECORDED[floor], require_shift=True)


@pytest.mark.parametrize('floor', FLOORS)
def test_short_real_run_does_not_invent_a_shift(tmp_path, monkeypatch, floor):
    pytest.importorskip('mujoco')
    monkeypatch.setenv('GEMINI_MODE', 'off')
    _, path = run_b2.run(seed=0, max_t=0.2, out_dir=tmp_path, floor=floor)
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    assert not any(row['kind'] == 'shift' for row in rows)
    assert_shift_floors(rows)


@pytest.mark.parametrize('mutation', ['missing', 'empty', 'ramp', 'numeric', 'wrong_floor', 'wrong_level'])
def test_incorrect_shift_floor_is_rejected(mutation):
    rows = copy.deepcopy(RECORDED['B2'])
    shift = next(row for row in rows if row['kind'] == 'shift')
    if mutation == 'missing':
        del shift['level']
        message = 'missing its level'
    elif mutation in ('empty', 'ramp', 'numeric'):
        shift['level'] = {'empty': '', 'ramp': 'ramp', 'numeric': 2}[mutation]
        message = 'invalid shift level'
    elif mutation == 'wrong_floor':
        shift['level'] = 'B1'
        message = 'wrong target floor'
    else:
        levels = [row for row in rows if row['kind'] == 'level']
        levels[-1]['level'] = 'B1'
        message = 'preceding level'
    with pytest.raises(AssertionError, match=message):
        assert_shift_floors(rows, require_shift=True)


# Genuine seed-0 B2/B3 logs generated into tmp on main 69f371c for this task.
# Projections retain actual kind/t/level and summary.floor; no floor key is
# invented on shift records, and no absent B1 slab shift is fabricated.
RECORDED = json.loads(r'''
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
      "t": 179.3,
      "kind": "summary",
      "floor": "B2"
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
      "t": 230.9,
      "kind": "summary",
      "floor": "B3"
    }
  ]
}
''')
