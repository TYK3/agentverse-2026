"""Validate real JSONL writers without adding a runtime validation dependency."""

import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import run_b2

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / 'coord/run_log_schema.json').read_text())


def valid(value, rule):
    """The small JSON Schema subset used here; unknown keywords fail explicitly."""
    supported = {'$ref', 'type', 'const', 'anyOf', 'properties', 'required',
                 'additionalProperties', 'enum', 'items', 'minItems', 'maxItems', 'minimum', 'minLength'}
    assert set(rule) <= supported, f'Unsupported validation keywords: {set(rule) - supported}'
    if '$ref' in rule:
        return valid(value, SCHEMA['$defs'][rule['$ref'].removeprefix('#/$defs/')])
    if 'anyOf' in rule and not any(valid(value, option) for option in rule['anyOf']):
        return False
    if 'enum' in rule and value not in rule['enum']:
        return False
    if 'const' in rule and value != rule['const']:
        return False
    types = {
        'object': isinstance(value, dict), 'array': isinstance(value, list),
        'number': type(value) in (int, float) and math.isfinite(value),
        'integer': type(value) is int, 'string': isinstance(value, str),
        'boolean': type(value) is bool, 'null': value is None,
    }
    if 'type' in rule:
        names = rule['type'] if isinstance(rule['type'], list) else [rule['type']]
        if not any(types[name] for name in names):
            return False
    if isinstance(value, dict):
        if not set(rule.get('required', [])) <= value.keys():
            return False
        properties = rule.get('properties', {})
        for key, item in value.items():
            child = properties.get(key, rule.get('additionalProperties', {}))
            if child is False or (isinstance(child, dict) and not valid(item, child)):
                return False
    if isinstance(value, list):
        if not rule.get('minItems', 0) <= len(value) <= rule.get('maxItems', math.inf):
            return False
        if not all(valid(item, rule.get('items', {})) for item in value):
            return False
    if isinstance(value, str) and len(value) < rule.get('minLength', 0):
        return False
    return not ('minimum' in rule and value < rule['minimum'])


def line_valid(row):
    return valid(row, {'anyOf': SCHEMA['anyOf']})


def test_recorder_real_writer(tmp_path):
    # Load the dependency-free writer without importing the MuJoCo sim package.
    spec = importlib.util.spec_from_file_location('run_log_recorder', ROOT / 'sim/recorder.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / 'recording.jsonl'
    writer = module.Recorder(path, SimpleNamespace(t=0.1))
    try:
        for fixture in sorted((ROOT / 'coord/fixtures').glob('*.json')):
            envelope = json.loads(fixture.read_text())
            writer.write(envelope['topic'], envelope['data'])
    finally:
        writer.close()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows
    assert all(line_valid(row) for row in rows)
    # demo60 uses the same envelope without wall, optionally with a rejection reason.
    for row in rows:
        del row['wall']
        assert line_valid(row)
        row['rejected'] = 'invalid payload'
        assert line_valid(row)


@pytest.mark.parametrize('seed', [0, 17])
@pytest.mark.parametrize('floor', ['B1', 'B2', 'B3'])
def test_short_real_b2_log(tmp_path, monkeypatch, floor, seed):
    pytest.importorskip('mujoco')
    monkeypatch.setenv('GEMINI_MODE', 'off')
    verdict, path = run_b2.run(seed=seed, max_t=0.2, out_dir=tmp_path, floor=floor)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    from sim import scene
    from sim.levels import LEVEL_Z, LEVELS, LevelWorld

    assert run_b2.evaluate(rows) == verdict
    assert rows[0]['topic'] == 'scene/loaded'
    assert rows[0]['t'] == 0
    loaded = rows[0]['data']
    expected = LevelWorld(path=tmp_path / 'levels_with_slab.xml', seed=seed, render=False)
    assert loaded['scene'] == LEVELS.stem
    assert loaded['blocks'] == scene.blocks(expected.m, expected.d)
    assert loaded['building_id'] == expected.m.names.split(b'\0', 1)[0].decode()
    assert loaded['floors'] == LEVEL_Z
    # Every configured floor has a real support surface in the loaded model.
    surfaces = [expected.d.geom_xpos[i][2] + expected.m.geom_size[i][2]
                for i in range(expected.m.ngeom) if '_floor' in expected.m.geom(i).name]
    assert all(any(math.isclose(z, top, abs_tol=1e-6) for top in surfaces) for z in loaded['floors'].values())
    assert loaded['robots'] == [expected.m.body(expected.scout).name]
    assert loaded['survivor_seed'] == seed
    kind_rows = [r for r in rows if 'kind' in r]
    assert {'level', 'pose', 'plan', 'summary', 'verdict'} <= {r['kind'] for r in kind_rows}
    for row in rows:
        assert line_valid(row), row
    summary = next(row for row in kind_rows if row['kind'] == 'summary')
    assert summary['floor'] == floor
    assert not line_valid(dict(summary, floor='B4'))
    assert not line_valid(dict(summary, floor=2))
    assert not line_valid(dict(summary, invented=True))
    # Older recordings predate --floor and must still validate.
    historical = dict(summary)
    del historical['floor']
    assert line_valid(historical)


@pytest.mark.parametrize('row', [
    {}, {'t': 0, 'topic': 'say'}, {'t': -1, 'topic': 'say', 'data': {}},
    {'t': True, 'topic': 'say', 'data': {}}, {'t': 0, 'topic': '', 'data': {}},
    {'t': 0, 'topic': 'say', 'data': {}, 'wall': -1}, {'t': 0, 'kind': 'unknown'},
    {'t': 0, 'kind': 'level', 'level': 3},
    {'t': 0, 'kind': 'level', 'level': 'B1', 'invented': 1},
    {'t': float('nan'), 'kind': 'level', 'level': 'B1'},
])
def test_rejects_malformed_records(row):
    assert not line_valid(row)
