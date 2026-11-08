"""LOG-HAS-SEED: a real run log records the seed it was run with.

Live `GEMINI_MODE=off python tools/run_b2.py --seed 0` took 21.3 s, so these
tests call the same `run()` with `--floor B1` (about 12 s). That writer appends
level, pose, plan, mapped and shift records, then a summary, then a verdict
line, to `<floor>-<seed>.jsonl`. coord/CONTRACT.md does not give that log a
seed field. The seed is only in the file name.

`console/tests/fixtures/b2-seed0.jsonl` is a saved B2 log (level, pose, plan,
shift, mapped, summary, verdict). Its body has no seed either. The runner does
not write one, so this module does not assert on that fixture.
"""

import json
import os

import pytest

from tools.run_b2 import run

SEEDS = (0, 1)
FLOOR = "B1"

# Two B1 runs are about 24 s. The mark is unregistered on purpose.
pytestmark = pytest.mark.slow


def records(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def seed_from_log(rows):
    """Seed on a header, summary, or verdict record. The file name does not count."""
    found = [
        row["seed"]
        for row in rows
        if row.get("kind") in {"header", "meta", "summary", "verdict"} and "seed" in row
    ]
    assert found, (
        "seed is missing from the log content; tools/run_b2.py run() writes "
        "level, pose, plan, mapped and shift records, then a summary record, "
        "then a verdict line, and none of them has a seed"
    )
    assert all(value == found[0] for value in found), found
    return found[0]


@pytest.fixture(scope="module")
def seed_logs(tmp_path_factory):
    pytest.importorskip("mujoco")
    out = tmp_path_factory.mktemp("log-has-seed")
    previous = os.environ.get("GEMINI_MODE")
    os.environ["GEMINI_MODE"] = "off"
    try:
        logged = []
        for seed in SEEDS:
            _verdict, path = run(seed=seed, out_dir=out, floor=FLOOR)
            text = path.read_text(encoding="utf-8")
            logged.append({"seed": seed, "path": path, "text": text, "rows": records(text)})
        return logged
    finally:
        if previous is None:
            os.environ.pop("GEMINI_MODE", None)
        else:
            os.environ["GEMINI_MODE"] = previous


def test_file_name_carries_its_own_seed(seed_logs):
    """The file name is the only place the seed appears.

    `run()` names the log `<floor>-<seed>.jsonl`. The body is asserted in
    `test_log_content_carries_its_own_seed`.
    """
    names = []
    for item in seed_logs:
        name = item["path"].name
        assert name == f"{FLOOR.lower()}-{item['seed']}.jsonl"
        assert int(name.removesuffix(".jsonl").rsplit("-", 1)[1]) == item["seed"]
        kinds = {row["kind"] for row in item["rows"]}
        assert {"summary", "verdict"} <= kinds
        names.append(name)
    assert names[0] != names[1]


def test_log_content_carries_its_own_seed(seed_logs):
    texts = []
    for item in seed_logs:
        assert seed_from_log(item["rows"]) == item["seed"]
        texts.append(item["text"])
    assert texts[0] != texts[1], "the two run logs are identical"
