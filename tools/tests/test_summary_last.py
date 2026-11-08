"""Public run() completion means the returned verdict is fully persisted after summary.

Unlike generic event ordering (#291), this checks returned metadata against the
actual bytes available immediately on return, including B1 and incomplete runs.
"""

import copy
import json
from pathlib import Path

import pytest

from tools import run_b2


def assert_completed_output(raw, returned):
    assert raw.endswith(b'\n'), 'completed JSONL must end with a newline'
    lines = raw.splitlines()
    assert lines and all(line.strip() for line in lines), 'blank record after completion'
    try:
        rows = [json.loads(line) for line in lines]
    except json.JSONDecodeError as exc:
        raise AssertionError('incomplete JSONL record at completion') from exc
    summaries = [i for i, row in enumerate(rows) if row['kind'] == 'summary']
    assert len(summaries) == 1, 'exactly one completed summary required'
    tail = rows[summaries[0] + 1:]
    assert len(tail) == 1 and tail[0]['kind'] == 'verdict', 'only verdict may follow summary'
    persisted = {k: v for k, v in tail[0].items() if k not in ('kind', 't')}
    assert persisted == returned, 'persisted verdict differs from run() return value'
    return rows


@pytest.mark.parametrize('floor', ['B1', 'B2', 'B3'])
def test_run_return_has_complete_matching_log_tail(tmp_path, monkeypatch, floor):
    pytest.importorskip('mujoco')
    monkeypatch.setenv('GEMINI_MODE', 'off')
    returned, path = run_b2.run(seed=0, max_t=0.2, out_dir=tmp_path, floor=floor)
    rows = assert_completed_output(Path(path).read_bytes(), returned)
    assert rows[-2]['floor'] == floor and rows[-2]['reached'] is False
    assert returned['failed'], 'truncated rescues still need a complete terminal record'


def test_genuine_recorded_wire_bytes_match_returned_verdict():
    assert_completed_output(RECORDED_WIRE, RECORDED_RETURN)


@pytest.mark.parametrize('mutation', ['unterminated', 'truncated_json', 'extra_record',
                                      'duplicate_summary', 'blank_tail', 'wrong_return'])
def test_completion_corruption_is_not_hidden(mutation):
    raw = RECORDED_WIRE
    returned = copy.deepcopy(RECORDED_RETURN)
    lines = raw.splitlines()
    if mutation == 'unterminated':
        raw = raw[:-1]
        message = 'end with a newline'
    elif mutation == 'truncated_json':
        raw = b'\n'.join([*lines[:-1], lines[-1][:-1]]) + b'\n'
        message = 'incomplete JSONL'
    elif mutation == 'extra_record':
        raw += lines[0] + b'\n'
        message = 'only verdict'
    elif mutation == 'duplicate_summary':
        raw = b'\n'.join([*lines[:-2], lines[-2], *lines[-2:]]) + b'\n'
        message = 'exactly one'
    elif mutation == 'blank_tail':
        raw += b'\n'
        message = 'blank record'
    else:
        returned['failed'] = []
        message = 'return value'
    with pytest.raises(AssertionError, match=message):
        assert_completed_output(raw, returned)


# Exact bytes and actual returned dict from a real B2 seed-0, max_t=0.2 run on
# main 69f371c. The run fails arrival, but its completion record is valid and whole.
RECORDED_WIRE = r'''
{"t": 0.0, "kind": "level", "level": "L1"}
{"t": 0.0, "kind": "pose", "pos": [0.5, 0.5, 0.675], "state": "idle", "level": "L1", "cell": [10, 10, 12]}
{"t": 0.0, "kind": "plan", "status": "explore", "why": "explore", "target": [0.53, 1.52, 0.6], "cells": [[10, 10, 12], [10, 11, 12], [10, 12, 12], [10, 13, 12], [10, 14, 12], [10, 15, 12], [10, 16, 12], [10, 17, 12], [10, 18, 12], [10, 19, 12], [10, 20, 12], [10, 21, 12], [10, 22, 12], [10, 23, 12], [10, 24, 12], [10, 25, 12], [10, 26, 12], [10, 27, 12], [10, 28, 12], [10, 29, 12], [10, 30, 12], [10, 31, 12], [10, 32, 12], [10, 33, 12], [10, 34, 12], [10, 35, 12], [10, 36, 12], [10, 37, 12], [10, 38, 12]]}
{"t": 0.2, "kind": "summary", "floor": "B2", "reached": false, "final_pos": [0.501, 0.56, 0.675], "final_level": "L1", "max_jump": 0.03, "route": "ok", "route_k": [12, 12]}
{"t": 0.2, "kind": "verdict", "steps": {"descended level by level to the target floor": {"ok": false, "t": null, "detail": "L1"}, "slab dropped on the planned route on the target floor": {"ok": false, "t": null, "detail": "no shift (route on B2 too short or never driven)"}, "Scout stopped short of the slab": {"ok": false, "t": null, "detail": "no shift"}, "slab mapped from the Scout's own measurements": {"ok": false, "t": null, "detail": "no shift"}, "re-planned route avoids the slab": {"ok": false, "t": null, "detail": "no shift"}, "Scout reached the casualty on the target floor": {"ok": false, "t": 0.2, "detail": "at [0.501, 0.56, 0.675] on L1"}, "Scout never entered the slab": {"ok": false, "t": null, "detail": "no shift"}, "no teleport": {"ok": true, "t": null, "detail": "max move 0.03 m per tick"}, "route over the scouted map from L1 to the target floor": {"ok": false, "t": null, "detail": "ok k [12, 12]"}}, "passed": ["no teleport"], "failed": ["descended level by level to the target floor", "slab dropped on the planned route on the target floor", "Scout stopped short of the slab", "slab mapped from the Scout's own measurements", "re-planned route avoids the slab", "Scout reached the casualty on the target floor", "Scout never entered the slab", "route over the scouted map from L1 to the target floor"]}
'''.lstrip().encode('utf-8')
RECORDED_RETURN = json.loads(r'''
{
  "steps": {
    "descended level by level to the target floor": {
      "ok": false,
      "t": null,
      "detail": "L1"
    },
    "slab dropped on the planned route on the target floor": {
      "ok": false,
      "t": null,
      "detail": "no shift (route on B2 too short or never driven)"
    },
    "Scout stopped short of the slab": {
      "ok": false,
      "t": null,
      "detail": "no shift"
    },
    "slab mapped from the Scout's own measurements": {
      "ok": false,
      "t": null,
      "detail": "no shift"
    },
    "re-planned route avoids the slab": {
      "ok": false,
      "t": null,
      "detail": "no shift"
    },
    "Scout reached the casualty on the target floor": {
      "ok": false,
      "t": 0.2,
      "detail": "at [0.501, 0.56, 0.675] on L1"
    },
    "Scout never entered the slab": {
      "ok": false,
      "t": null,
      "detail": "no shift"
    },
    "no teleport": {
      "ok": true,
      "t": null,
      "detail": "max move 0.03 m per tick"
    },
    "route over the scouted map from L1 to the target floor": {
      "ok": false,
      "t": null,
      "detail": "ok k [12, 12]"
    }
  },
  "passed": [
    "no teleport"
  ],
  "failed": [
    "descended level by level to the target floor",
    "slab dropped on the planned route on the target floor",
    "Scout stopped short of the slab",
    "slab mapped from the Scout's own measurements",
    "re-planned route avoids the slab",
    "Scout reached the casualty on the target floor",
    "Scout never entered the slab",
    "route over the scouted map from L1 to the target floor"
  ]
}
''')
