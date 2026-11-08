"""VERDICT-HAS-FLOOR: the real verdict names the floor actually finished on.

The current run-log schema forbids extra top-level verdict fields. Its existing
completion-step `detail` names the final floor instead. Verify that public
representation in both the returned and persisted verdict, against the real
summary and final pose for B2/B3 (not just a hard-coded default target). This
does not establish a new structured `verdict.floor` field or cover failed runs.
"""

import json
import re

import pytest

from tools import run_b2

FLOOR_Z = {"B2": -1.2, "B3": -1.8}


def assert_verdict_names_finished_floor(verdict, floor):
    completion = verdict["steps"][run_b2.STEPS[5]]
    assert completion["ok"] is True, completion
    mentions = re.findall(r"\b(?:L1|ground|B1|B2|B3|ramp)\b", completion["detail"])
    assert mentions == [floor], ("missing, wrong or ambiguous final floor", completion)


@pytest.mark.parametrize("floor", ["B2", "B3"])
def test_real_verdict_names_its_actual_finished_floor(tmp_path, floor):
    verdict, path = run_b2.run(seed=0, max_t=500.0, out_dir=tmp_path, floor=floor)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert verdict["failed"] == [], verdict
    summaries = [r for r in records if r["kind"] == "summary"]
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["reached"] is True and summary["final_level"] == floor, summary
    assert abs(summary["final_pos"][2] - (FLOOR_Z[floor] + 0.075)) < 0.003, summary
    final_pose = next(r for r in reversed(records) if r["kind"] == "pose")
    assert final_pose["level"] == floor, final_pose
    assert abs(final_pose["pos"][2] - (FLOOR_Z[floor] + 0.075)) < 0.021, final_pose

    saved = [r for r in records if r["kind"] == "verdict"]
    assert len(saved) == 1
    persisted = saved[0]
    assert persisted["t"] == summary["t"]
    assert {key: persisted[key] for key in ("steps", "passed", "failed")} == verdict
    for result in (verdict, persisted):
        assert_verdict_names_finished_floor(result, summary["final_level"])
