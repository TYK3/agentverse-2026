"""A demo log must carry both a passing runner verdict and replayable evidence."""

import json

from tools.check_demo import check


def write_log(path, records):
    path.write_text("\n".join(json.dumps({"t": i, "topic": topic, "data": data})
                              for i, (topic, data) in enumerate(records)) + "\n", encoding="utf-8")


def good_records():
    return [
        ("scene/loaded", {"scene": "levels", "blocks": []}),
        ("map/casualties", [{"id": "c1", "pos": [1, 2, -0.6]}]),
        ("route/verified", {"id": "r1", "ok": True}),
        ("permit/route", {"route": "r1", "granted": True}),
        ("world/change", {"kind": "block_added"}),
        ("permit/route", {"route": "r1", "granted": False}),
        ("permit/route", {"route": "r2", "granted": True}),
        ("responder/action", {"action": "place_supply", "route": "r2"}),
        ("report/handover", {"json": {}, "markdown": "# Handover"}),
        ("_runner/stage", {"stage": "b1", "reached": True}),
        *(("_runner/step", {"step": f"step {n}", "ok": True}) for n in range(16)),
        ("_runner/summary", {"passed": 16, "failed": [], "messages": {}}),
    ]


def test_accepts_complete_b1_recording(tmp_path):
    path = tmp_path / "run.jsonl"
    write_log(path, good_records())
    assert check(path) == []


def test_rejects_failed_or_truncated_recording(tmp_path):
    path = tmp_path / "run.jsonl"
    records = good_records()
    records[-2] = ("_runner/step", {"step": "handover report", "ok": False})
    records.pop()
    write_log(path, records)
    errors = check(path)
    assert any("runner steps failed" in error for error in errors)
    assert any("final _runner/summary" in error for error in errors)


def test_rejects_missing_replay_evidence_even_with_pass_summary(tmp_path):
    path = tmp_path / "run.jsonl"
    records = [record for record in good_records() if record[0] != "world/change"]
    write_log(path, records)
    assert "missing world/change" in check(path)
