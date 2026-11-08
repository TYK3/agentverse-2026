"""VERDICT-HAS-SEED: the verdict line of a real run log names the seed that produced the run.

One real tools/run_b2.py B2 run at seed 3 (not the default 0, so a hard-coded seed cannot pass), about 30 s.
The verdict is the log's last line. Today nothing in the log names the seed: not the verdict, not the
summary, no other record. Only the file name does (runs/b2-<seed>.jsonl), and B2 logs are byte-identical
across seeds (board, #265), so a renamed or copied log cannot be traced back to its run.

The seed tests are strict xfails for that gap. Closing it needs a "seed" field written by run_b2.py on the
verdict (tools/, its owner) and allowed by coord/run_log_schema.json's verdict (additionalProperties is
false there; coord/, the lead). When both land, the xfails turn red: remove the markers.
"""

import json

import pytest

from tools.tests.test_run_log_schema import SCHEMA, valid

SEED = 3
GAP = "run_b2.py writes no seed on the verdict and run_log_schema.json's verdict does not allow one"


@pytest.fixture(scope="module")
def log(tmp_path_factory):
    pytest.importorskip("mujoco")
    from tools import run_b2

    verdict, path = run_b2.run(seed=SEED, out_dir=tmp_path_factory.mktemp("b2"))
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return path, records, verdict


def test_the_real_log_ends_with_its_one_verdict(log):
    path, records, verdict = log
    assert path.name == f"b2-{SEED}.jsonl"
    assert [r["kind"] for r in records].count("verdict") == 1
    last = records[-1]
    assert last["kind"] == "verdict"
    assert {k: last[k] for k in ("steps", "passed", "failed")} == verdict


@pytest.mark.xfail(strict=True, reason=GAP)
def test_the_verdict_names_the_seed_that_produced_the_run(log):
    path, records, _ = log
    verdict = records[-1]
    assert verdict.get("seed") == SEED, f"verdict keys: {sorted(verdict)}"
    assert path.name == f"b2-{verdict['seed']}.jsonl", "the file name and the verdict agree"


@pytest.mark.xfail(strict=True, reason=GAP)
def test_a_verdict_with_its_seed_is_a_valid_run_log_record(log):
    verdict = {**log[1][-1], "seed": SEED}
    assert valid(verdict, SCHEMA["$defs"]["verdict"])


def test_no_other_record_names_the_seed_either(log):
    """Why the verdict must carry it: today the seed is nowhere inside the log."""
    _, records, _ = log
    before = records[:-1]                                            # everything but the verdict line
    assert not any("seed" in r for r in before), "if another record gained a seed, check it agrees too"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
