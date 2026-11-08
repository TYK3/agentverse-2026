"""MAPPED-HAS-T: every `mapped` record in a real run log carries a usable sim time (ref b3).

`mapped` says when the slab got into the Scout's map from its own measurements. Each one must have:
- t: a finite number (not a bool, NaN or infinity),
- at or after the slab shift it is about (it cannot be mapped before it lands), at most STOP_WINDOW
  later (the runner's own window for the stop),
- inside the run: between the first and the last record's t.
And there is at least one `mapped` record in a run with a shift.

Real logs: REAL (seed 0 on main, both 9/9): the first and last records, levels, shift, mapped and summary
of a B2 run and a B3 run; plus full runs/b2-*.jsonl and runs/b3-*.jsonl (or $B2_LOG / $B3_LOG) when
present (they skip otherwise; CI has none).
"""

import json
import math
import os
import pathlib

import pytest

from tools.run_b2 import STOP_WINDOW

ROOT = pathlib.Path(__file__).resolve().parents[2]

def _full(name):
    """The newest full runs/<name>-*.jsonl (or $B2_LOG / $B3_LOG), or skip."""
    env = os.environ.get(f"{name.upper()}_LOG")
    found = [pathlib.Path(env)] if env else sorted((ROOT / "runs").glob(f"{name}-*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not found:
        pytest.skip(f"no full {name.upper()} log")
    return [json.loads(line) for line in found[-1].read_text(encoding="utf-8").splitlines() if line.strip()]


REAL = {
    'b2-0': [
        {'t': 0.0, 'kind': 'level', 'level': 'L1'},
        {'t': 21.6, 'kind': 'level', 'level': 'ground'},
        {'t': 80.1, 'kind': 'level', 'level': 'B1'},
        {'t': 155.3, 'kind': 'level', 'level': 'B2'},
        {'t': 173.6, 'kind': 'shift', 'xy': [1.125, 0.975], 'level': 'B2', 'core': [[20, 17], [20, 18], [20, 19], [20, 20], [20, 21], [21, 17], [21, 18], [21, 19], [21, 20], [21, 21], [22, 17], [22, 18], [22, 19], [22, 20], [22, 21], [23, 17], [23, 18], [23, 19], [23, 20], [23, 21], [24, 17], [24, 18], [24, 19], [24, 20], [24, 21]], 'scout': [1.395, 1.107, -1.125]},
        {'t': 173.7, 'kind': 'mapped', 'cells': 5, 'sources': ['lidar', 'refused']},
        {'t': 179.3, 'kind': 'summary', 'floor': 'B2', 'reached': True, 'final_pos': [0.777, 0.823, -1.125], 'final_level': 'B2', 'max_jump': 0.0313, 'route': 'ok', 'route_k': [12, -24]},
        {'t': 179.3, 'kind': 'verdict', 'steps': {'descended level by level to the target floor': {'ok': True, 't': None, 'detail': 'L1 -> ground -> B1 -> B2'}, 'slab dropped on the planned route on the target floor': {'ok': True, 't': 173.6, 'detail': 'slab at [1.125, 0.975] on B2'}, 'Scout stopped short of the slab': {'ok': True, 't': 175.0, 'detail': 'state arrived'}, "slab mapped from the Scout's own measurements": {'ok': True, 't': 173.7, 'detail': "5 occupied cell(s) in the slab's footprint (lidar, refused)"}, 're-planned route avoids the slab': {'ok': True, 't': 173.7, 'detail': '11/11 planned paths after the shift avoid it'}, 'Scout reached the casualty on the target floor': {'ok': True, 't': 179.3, 'detail': 'at [0.777, 0.823, -1.125] on B2'}, 'Scout never entered the slab': {'ok': True, 't': None, 'detail': 'never inside it'}, 'no teleport': {'ok': True, 't': None, 'detail': 'max move 0.0313 m per tick'}, 'route over the scouted map from L1 to the target floor': {'ok': True, 't': None, 'detail': 'ok k [12, -24]'}}, 'passed': ['descended level by level to the target floor', 'slab dropped on the planned route on the target floor', 'Scout stopped short of the slab', "slab mapped from the Scout's own measurements", 're-planned route avoids the slab', 'Scout reached the casualty on the target floor', 'Scout never entered the slab', 'no teleport', 'route over the scouted map from L1 to the target floor'], 'failed': []},
    ],
    'b3-0': [
        {'t': 0.0, 'kind': 'level', 'level': 'L1'},
        {'t': 21.6, 'kind': 'level', 'level': 'ground'},
        {'t': 65.9, 'kind': 'level', 'level': 'B1'},
        {'t': 142.9, 'kind': 'level', 'level': 'B2'},
        {'t': 217.0, 'kind': 'level', 'level': 'B3'},
        {'t': 225.8, 'kind': 'shift', 'xy': [0.675, 0.925], 'level': 'B3', 'core': [[11, 16], [11, 17], [11, 18], [11, 19], [11, 20], [12, 16], [12, 17], [12, 18], [12, 19], [12, 20], [13, 16], [13, 17], [13, 18], [13, 19], [13, 20], [14, 16], [14, 17], [14, 18], [14, 19], [14, 20], [15, 16], [15, 17], [15, 18], [15, 19], [15, 20]], 'scout': [0.678, 0.622, -1.725]},
        {'t': 226.0, 'kind': 'mapped', 'cells': 4, 'sources': ['lidar', 'refused']},
        {'t': 230.9, 'kind': 'summary', 'floor': 'B3', 'reached': True, 'final_pos': [0.825, 1.525, -1.725], 'final_level': 'B3', 'max_jump': 0.0313, 'route': 'ok', 'route_k': [12, -36]},
        {'t': 230.9, 'kind': 'verdict', 'steps': {'descended level by level to the target floor': {'ok': True, 't': None, 'detail': 'L1 -> ground -> B1 -> B2 -> B3'}, 'slab dropped on the planned route on the target floor': {'ok': True, 't': 225.8, 'detail': 'slab at [0.675, 0.925] on B3'}, 'Scout stopped short of the slab': {'ok': True, 't': 226.0, 'detail': 'state blocked'}, "slab mapped from the Scout's own measurements": {'ok': True, 't': 226.0, 'detail': "4 occupied cell(s) in the slab's footprint (lidar, refused)"}, 're-planned route avoids the slab': {'ok': True, 't': 226.0, 'detail': '6/6 planned paths after the shift avoid it'}, 'Scout reached the casualty on the target floor': {'ok': True, 't': 230.9, 'detail': 'at [0.825, 1.525, -1.725] on B3'}, 'Scout never entered the slab': {'ok': True, 't': None, 'detail': 'never inside it'}, 'no teleport': {'ok': True, 't': None, 'detail': 'max move 0.0313 m per tick'}, 'route over the scouted map from L1 to the target floor': {'ok': True, 't': None, 'detail': 'ok k [12, -36]'}}, 'passed': ['descended level by level to the target floor', 'slab dropped on the planned route on the target floor', 'Scout stopped short of the slab', "slab mapped from the Scout's own measurements", 're-planned route avoids the slab', 'Scout reached the casualty on the target floor', 'Scout never entered the slab', 'no teleport', 'route over the scouted map from L1 to the target floor'], 'failed': []},
    ],
}


def mapped_times(records):
    """[(t, problem or None)] for each mapped record."""
    shift = next((r["t"] for r in records if r.get("kind") == "shift"), None)
    ts = [r["t"] for r in records if isinstance(r.get("t"), (int, float)) and not isinstance(r.get("t"), bool)
          and math.isfinite(r["t"])]
    first, last = (min(ts), max(ts)) if ts else (None, None)
    out = []
    for r in records:
        if r.get("kind") != "mapped":
            continue
        t = r.get("t")
        if not isinstance(t, (int, float)) or isinstance(t, bool) or not math.isfinite(t):
            out.append((t, "no finite t"))
        elif shift is None or t < shift:
            out.append((t, f"before the shift at {shift}"))
        elif t > shift + STOP_WINDOW:
            out.append((t, f"more than {STOP_WINDOW} s after the shift at {shift}"))
        elif not first <= t <= last:
            out.append((t, "outside the run"))
        else:
            out.append((t, None))
    return out


def check(records):
    got = mapped_times(records)
    assert got, "no mapped record"
    assert [p for _, p in got if p] == [], got
    return [t for t, _ in got]


def test_real_logs():
    assert check(REAL["b2-0"]) == [173.7]                        # shift 173.6
    assert check(REAL["b3-0"]) == [226.0]                        # shift 225.8


@pytest.mark.parametrize("name", ["b2", "b3"])
def test_full_real_logs(name):
    print(name, check(_full(name)))


def _with_t(t):
    recs = json.loads(json.dumps(REAL["b2-0"]))
    next(r for r in recs if r["kind"] == "mapped")["t"] = t
    return recs


@pytest.mark.parametrize("records", [
    _with_t(None), _with_t("173.7"), _with_t(True),               # no number
    _with_t(173.5),                                               # before the shift at 173.6
    _with_t(173.6 + STOP_WINDOW + 0.5),                           # long after it
    [r for r in REAL["b2-0"] if r["kind"] != "mapped"],           # never mapped
])
def test_bad_or_missing_mapped_t_fails(records):
    with pytest.raises(AssertionError):
        check(records)


def test_nan_written_to_a_real_file_is_caught(tmp_path):
    path = tmp_path / "x.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in _with_t(float("nan"))) + "\n", encoding="utf-8")
    back = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    with pytest.raises(AssertionError):
        check(back)
