"""Every vitals field in the repo is labelled simulated (ref VITALS-LABELLED)."""

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from coord.messages import Vitals, validate_payload
from perception.casualties import VITALS
from planner.report import ReportCollector

ROOT = Path(__file__).resolve().parents[2]
# Real files that break the rule: path -> reason. Each is a strict xfail.
KNOWN: dict[str, str] = {}


def tracked_files():
    out = subprocess.run(["git", "ls-files", "*.json", "*.jsonl"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return sorted(p for p in out.splitlines() if (ROOT / p).is_file())


def records(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    if path.endswith(".jsonl"):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return [json.loads(text)]


def vitals_in(node, where="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "vitals" and isinstance(value, dict):
                yield where, value
            yield from vitals_in(value, f"{where}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from vitals_in(value, f"{where}[{i}]")


FILES = [p for p in tracked_files() if any(True for r in records(p) for _ in vitals_in(r))]


def test_vitals_instances_found():
    assert FILES, "no tracked json/jsonl file carries a vitals object"
    assert "coord/fixtures/map__casualties.json" in FILES


@pytest.mark.parametrize("path", [
    pytest.param(p, marks=pytest.mark.xfail(strict=True, reason=KNOWN[p])) if p in KNOWN else p
    for p in FILES])
def test_tracked_vitals_simulated(path):
    bad = [where for r in records(path) for where, v in vitals_in(r) if v.get("simulated") is not True]
    assert not bad, f"{path}: vitals not marked simulated at {bad}"


def test_perception_vitals_simulated():
    assert VITALS["simulated"] is True


def test_model_requires_simulated_true():
    assert Vitals(breathing_rate=14, simulated=True).simulated is True
    for bad in ({"breathing_rate": 14}, {"breathing_rate": 14, "simulated": False}):
        with pytest.raises(ValidationError):
            Vitals(**bad)
    cas = {"id": "c1", "pos": [0, 0, 0], "confidence": 0.8, "clues": [], "vitals": {"breathing_rate": 14}}
    with pytest.raises(ValidationError):
        validate_payload("map/casualties", [cas])


def test_report_forces_simulated(tmp_path):
    class Bus:
        def __getattr__(self, name):
            return lambda *a, **k: None

    collector = ReportCollector(Bus(), output_dir=tmp_path)
    collector.on_casualties([{"id": "c1", "pos": [0, 0, 0], "confidence": 0.8, "clues": [],
                              "vitals": {"breathing_rate": 14, "simulated": False}}])
    assert all(c["vitals"]["simulated"] is True for c in collector.casualties)
