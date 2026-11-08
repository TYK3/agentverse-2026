"""Cross-check recorded verdict metadata, not an invented summary-only success flag."""

import copy
import json
from pathlib import Path

import pytest

from tools import run_b2

ARRIVAL = 'Scout reached the casualty on the target floor'
CONTINUITY = 'no teleport'
ROUTE = 'route over the scouted map from L1 to the target floor'


def assert_agreement(rows):
    summaries = [r for r in rows if r['kind'] == 'summary']
    verdicts = [r for r in rows if r['kind'] == 'verdict']
    assert len(summaries) == len(verdicts) == 1, 'one summary and one verdict required'
    summary, verdict = summaries[0], verdicts[0]
    assert summary['t'] == verdict['t'], 'summary/verdict final times disagree'
    steps = verdict['steps']
    assert len(steps) == 9 and set(steps) == set(run_b2.STEPS), 'nine named checks required'
    for step in steps.values():
        assert type(step['ok']) is bool, 'check outcome must be boolean'
    passed = [name for name in run_b2.STEPS if steps[name]['ok']]
    failed = [name for name in run_b2.STEPS if not steps[name]['ok']]
    assert verdict['passed'] == passed, 'passed list disagrees with check outcomes'
    assert verdict['failed'] == failed, 'failed list disagrees with check outcomes'
    assert len(verdict['passed']) + len(verdict['failed']) == 9, 'check counts disagree'
    assert steps[ARRIVAL]['ok'] is (summary['reached'] is True), 'arrival disagrees with summary'
    jump = summary['max_jump']
    assert steps[CONTINUITY]['ok'] is (jump is not None and jump <= 0.035), 'jump check disagrees'
    bottom = {'B1': -12, 'B2': -24, 'B3': -36}[summary['floor']]
    span = summary['route_k']
    route_ok = bool(summary['route'] == 'ok' and span and span[1] <= bottom)
    assert steps[ROUTE]['ok'] is route_ok, 'route span disagrees with summary'
    # Other checks require level/shift/pose/map/plan events, not summary booleans.
    assert (not verdict['failed']) is all(s['ok'] for s in steps.values())


@pytest.mark.parametrize('floor', ['B2', 'B3'])
def test_short_real_summary_and_verdict_agree(tmp_path, monkeypatch, floor):
    pytest.importorskip('mujoco')
    monkeypatch.setenv('GEMINI_MODE', 'off')
    _, path = run_b2.run(seed=0, max_t=0.2, out_dir=tmp_path, floor=floor)
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    assert_agreement(rows)
    verdict = rows[-1]
    # At 0.2 sim seconds only continuity passes: no basement or slab has been reached.
    assert verdict['passed'] == [CONTINUITY]
    assert len(verdict['failed']) == 8


@pytest.mark.parametrize('floor', ['B2', 'B3'])
def test_complete_recorded_runs_agree(floor):
    # Actual seed-0 summary/verdict pairs; projection retains all outcomes and counts.
    assert_agreement(RECORDED_PAIRS[floor])
    assert len(RECORDED_PAIRS[floor][-1]['passed']) == 9
    assert RECORDED_PAIRS[floor][-1]['failed'] == []


@pytest.mark.parametrize(('field', 'value', 'message'), [
    ('reached', False, 'arrival'), ('max_jump', 0.036, 'jump'),
    ('route', 'blocked', 'route span'), ('route_k', [12, 12], 'route span'),
])
def test_summary_contradictions_are_rejected(field, value, message):
    rows = copy.deepcopy(RECORDED_PAIRS['B2'])
    rows[0][field] = value
    with pytest.raises(AssertionError, match=message):
        assert_agreement(rows)


def test_passed_counts_cannot_hide_a_failed_check():
    rows = copy.deepcopy(RECORDED_PAIRS['B2'])
    rows[-1]['steps'][ARRIVAL]['ok'] = False
    with pytest.raises(AssertionError, match='passed list'):
        assert_agreement(rows)


# Projected from real full logs on main 8411ab5, generated with:
# GEMINI_MODE=off python tools/run_b2.py --seed 0 --floor B2 (and --floor B3).
# Only per-check detail/t strings are omitted; the real outcomes are unchanged.
RECORDED_PAIRS = json.loads(r'''
{
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
  ],
  "B3": [
    {
      "t": 230.9,
      "kind": "summary",
      "floor": "B3",
      "reached": true,
      "final_pos": [
        0.825,
        1.525,
        -1.725
      ],
      "final_level": "B3",
      "max_jump": 0.0313,
      "route": "ok",
      "route_k": [
        12,
        -36
      ]
    },
    {
      "t": 230.9,
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
