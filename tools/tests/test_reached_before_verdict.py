"""Arrival is summary.reached, not an invented event or an overall success verdict."""

import copy
import json
from pathlib import Path

import pytest

from tools import run_b2

ARRIVAL = 'Scout reached the casualty on the target floor'


def assert_arrival_order(rows, expected):
    arrivals = [i for i, row in enumerate(rows) if row['kind'] == 'summary' and row['reached'] is True]
    verdicts = [i for i, row in enumerate(rows) if row['kind'] == 'verdict']
    assert len(verdicts) == 1, 'one final verdict required'
    index = verdicts[0]
    assert rows[index]['steps'][ARRIVAL]['ok'] is expected, 'verdict arrival check disagrees'
    if expected:
        assert len(arrivals) == 1, 'missing reached/at-casualty summary'
        arrival = arrivals[0]
        assert arrival < index, 'reached summary must precede verdict in file order'
        assert rows[arrival]['t'] <= rows[index]['t'], 'arrival time is after verdict time'
        assert rows[arrival]['final_level'] == rows[arrival]['floor'], 'arrival is on wrong floor'
    else:
        assert not arrivals, 'false or absent arrival must not be reported as reached'


@pytest.mark.parametrize('floor', ['B1', 'B2'])
def test_real_positive_arrival_precedes_verdict(floor):
    assert_arrival_order(RECORDED[floor], expected=True)
    # Both records share the final sim time: file order, not strict t inequality, matters.
    assert RECORDED[floor][0]['t'] == RECORDED[floor][1]['t']


@pytest.mark.parametrize('floor', ['B1', 'B2'])
def test_short_real_run_does_not_fabricate_arrival(tmp_path, monkeypatch, floor):
    pytest.importorskip('mujoco')
    monkeypatch.setenv('GEMINI_MODE', 'off')
    _, path = run_b2.run(seed=0, max_t=0.2, out_dir=tmp_path, floor=floor)
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    assert_arrival_order(rows, expected=False)
    assert next(row for row in rows if row['kind'] == 'summary')['reached'] is False


@pytest.mark.parametrize('mutation', ['verdict_first', 'no_arrival', 'late_time', 'wrong_floor'])
def test_invalid_arrival_order_has_a_clear_failure(mutation):
    rows = copy.deepcopy(RECORDED['B2'])
    if mutation == 'verdict_first':
        rows.reverse()
        message = 'precede verdict'
    elif mutation == 'no_arrival':
        rows[0]['reached'] = False
        message = 'missing reached'
    elif mutation == 'late_time':
        rows[0]['t'] += 0.1
        message = 'arrival time'
    else:
        rows[0]['final_level'] = 'L1'
        message = 'wrong floor'
    with pytest.raises(AssertionError, match=message):
        assert_arrival_order(rows, expected=True)


# Real seed-0 summary/verdict projections; only per-check details/t are omitted.
# B1 generated on 69f371c; B2 on 8411ab5. run_b2.py has the same blob on both.
# B1 genuinely arrived but failed five OTHER checks; reaching is not whole-run success.
RECORDED = json.loads(r'''
{
  "B1": [
    {
      "t": 88.7,
      "kind": "summary",
      "floor": "B1",
      "reached": true,
      "final_pos": [
        0.732,
        1.476,
        -0.525
      ],
      "final_level": "B1",
      "max_jump": 0.0313,
      "route": "ok",
      "route_k": [
        12,
        -12
      ]
    },
    {
      "t": 88.7,
      "kind": "verdict",
      "steps": {
        "descended level by level to the target floor": {
          "ok": true
        },
        "slab dropped on the planned route on the target floor": {
          "ok": false
        },
        "Scout stopped short of the slab": {
          "ok": false
        },
        "slab mapped from the Scout's own measurements": {
          "ok": false
        },
        "re-planned route avoids the slab": {
          "ok": false
        },
        "Scout reached the casualty on the target floor": {
          "ok": true
        },
        "Scout never entered the slab": {
          "ok": false
        },
        "no teleport": {
          "ok": true
        },
        "route over the scouted map from L1 to the target floor": {
          "ok": true
        }
      },
      "passed": [
        "descended level by level to the target floor",
        "Scout reached the casualty on the target floor",
        "no teleport",
        "route over the scouted map from L1 to the target floor"
      ],
      "failed": [
        "slab dropped on the planned route on the target floor",
        "Scout stopped short of the slab",
        "slab mapped from the Scout's own measurements",
        "re-planned route avoids the slab",
        "Scout never entered the slab"
      ]
    }
  ],
  "B2": [
    {
      "t": 179.3,
      "kind": "summary",
      "floor": "B2",
      "reached": true,
      "final_pos": [
        0.777,
        0.823,
        -1.125
      ],
      "final_level": "B2",
      "max_jump": 0.0313,
      "route": "ok",
      "route_k": [
        12,
        -24
      ]
    },
    {
      "t": 179.3,
      "kind": "verdict",
      "steps": {
        "descended level by level to the target floor": {
          "ok": true
        },
        "slab dropped on the planned route on the target floor": {
          "ok": true
        },
        "Scout stopped short of the slab": {
          "ok": true
        },
        "slab mapped from the Scout's own measurements": {
          "ok": true
        },
        "re-planned route avoids the slab": {
          "ok": true
        },
        "Scout reached the casualty on the target floor": {
          "ok": true
        },
        "Scout never entered the slab": {
          "ok": true
        },
        "no teleport": {
          "ok": true
        },
        "route over the scouted map from L1 to the target floor": {
          "ok": true
        }
      },
      "passed": [
        "descended level by level to the target floor",
        "slab dropped on the planned route on the target floor",
        "Scout stopped short of the slab",
        "slab mapped from the Scout's own measurements",
        "re-planned route avoids the slab",
        "Scout reached the casualty on the target floor",
        "Scout never entered the slab",
        "no teleport",
        "route over the scouted map from L1 to the target floor"
      ],
      "failed": []
    }
  ]
}
''')
