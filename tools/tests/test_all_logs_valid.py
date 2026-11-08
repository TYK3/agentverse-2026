"""Every JSONL run-log fixture tracked in the repo validates against coord/run_log_schema.json."""

import json
import subprocess
from pathlib import Path

import pytest

from tools.tests.test_run_log_schema import line_valid

ROOT = Path(__file__).resolve().parents[2]

# Tracked files that predate or sit outside the schema. They are listed here
# rather than skipped so the gap stays visible; strict xfail flags the entry
# for removal as soon as the file (or the schema) is brought into line.
KNOWN_NONCONFORMING = {
    'perception/fixtures/scout_backup_standin.jsonl': 'bus envelopes without top-level t',
    'sim/recordings/scout_backup.jsonl': 'bus envelopes without top-level t',
    'sim/recordings/scout_tower.jsonl': 'bus envelopes without top-level t',
    'tools/tests/golden/b1_descent.jsonl': 'demo_descent meta/event rows, not a schema kind',
}


def discover():
    """All git-tracked *.jsonl files, so new fixtures are picked up automatically."""
    try:
        out = subprocess.run(['git', 'ls-files', '*.jsonl'], cwd=ROOT, check=True,
                             capture_output=True, text=True).stdout
        files = out.split()
    except (OSError, subprocess.CalledProcessError):
        skip = {'.git', 'node_modules', '.venv', '.gem_cache'}
        files = [p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*.jsonl')
                 if not skip & set(p.relative_to(ROOT).parts)]
    return sorted(files)


FIXTURES = discover()


def test_fixtures_found():
    assert FIXTURES, 'no *.jsonl run-log fixtures found in the repo'


def test_known_nonconforming_entries_exist():
    missing = set(KNOWN_NONCONFORMING) - set(FIXTURES)
    assert not missing, f'stale KNOWN_NONCONFORMING entries: {sorted(missing)}'


@pytest.mark.parametrize('rel', [
    pytest.param(rel, marks=pytest.mark.xfail(reason=KNOWN_NONCONFORMING[rel], strict=True))
    if rel in KNOWN_NONCONFORMING else rel
    for rel in FIXTURES
])
def test_run_log_fixture_valid(rel):
    lines = (ROOT / rel).read_text().splitlines()
    rows = [(n, line) for n, line in enumerate(lines, 1) if line.strip()]
    assert rows, f'{rel} is empty'
    bad = []
    for n, line in rows:
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            bad.append(f'line {n}: invalid JSON ({exc.msg})')
            continue
        if not line_valid(row):
            bad.append(f'line {n}: {line[:120]}')
    assert not bad, f'{rel}: {len(bad)}/{len(rows)} lines fail run_log_schema, first: ' + '; '.join(bad[:3])
