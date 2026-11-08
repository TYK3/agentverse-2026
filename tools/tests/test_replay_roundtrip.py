"""REPLAY-ROUNDTRIP: JSONL disk boundaries and offline text-cache replay.

Recorder checks bus envelopes, not console pacing; the committed B2 log checks
ordered run events and the evaluator, not a new physics run. Cache replay checks
exact text and no provider access, not live generation.
"""

import importlib.util
import json
import socket
from collections import Counter, deque
from types import SimpleNamespace

import pytest

from coord import gem
from tools import run_b2
from tools.tests.test_run_log_schema import ROOT, line_valid


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def roundtrip(rows, path):
    assert rows
    for index, row in enumerate(rows):
        assert line_valid(row), (index, row)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")
    replayed = read_rows(path)
    assert replayed == rows  # includes order, timestamps, topics, payloads and optional fields
    assert all(line_valid(row) for row in replayed)
    return replayed


def test_bus_recording_roundtrip(tmp_path, monkeypatch):
    # Same dependency-free loading seam as test_run_log_schema: no MuJoCo required.
    spec = importlib.util.spec_from_file_location("roundtrip_recorder", ROOT / "sim/recorder.py")
    recorder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recorder)
    monkeypatch.setattr(recorder.time, "monotonic", lambda: 10.0)
    world = SimpleNamespace(t=0.0)
    path = tmp_path / "bus.jsonl"
    writer = recorder.Recorder(path, world, full=True)
    expected = []
    try:
        for index, fixture in enumerate(sorted((ROOT / "coord/fixtures").glob("*.json"))):
            envelope = json.loads(fixture.read_text(encoding="utf-8"))
            world.t = index * 0.125
            writer.on(envelope["topic"])(envelope["data"])
            expected.append({"t": world.t, "wall": 0.0, **envelope})
    finally:
        writer.close()
    assert read_rows(path) == expected
    replayed = roundtrip(expected, tmp_path / "bus-replayed.jsonl")
    summary = recorder.summary(tmp_path / "bus-replayed.jsonl")
    assert summary["topics"] == dict(Counter(row["topic"] for row in replayed))
    assert (summary["t0"], summary["t1"]) == (expected[0]["t"], expected[-1]["t"])


def test_committed_b2_run_roundtrip(tmp_path):
    rows = read_rows(ROOT / "console/tests/fixtures/b2-seed0.jsonl")
    replayed = roundtrip(rows, tmp_path / "b2-replayed.jsonl")
    assert {"level", "pose", "plan", "shift", "summary", "verdict"} <= {
        row["kind"] for row in replayed
    }
    verdict = next(row for row in rows if row["kind"] == "verdict")
    evaluated = run_b2.evaluate(replayed)
    # Historical verdict labels predate floor-generic evaluator labels.
    assert evaluated == run_b2.evaluate(rows)
    assert verdict["failed"] == []
    assert len(evaluated["passed"]) == len(verdict["passed"]) == 9
    assert evaluated["failed"] == []


@pytest.mark.parametrize("text", ["", "Water delivered: café — 救援\nsecond line\r\n"])
def test_gem_cached_text_roundtrip(tmp_path, monkeypatch, text):
    monkeypatch.setenv("GEMINI_MODE", "replay")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(gem, "MODE", "replay")
    monkeypatch.setattr(gem, "CACHE", tmp_path)
    monkeypatch.setattr(gem, "_receipts", deque(maxlen=200))

    def no_network(*args, **kwargs):
        pytest.fail("cache replay attempted a provider/network call")

    monkeypatch.setattr(gem, "_c", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    request = "Return the recorded rescue status."
    cache = gem._cache_file("fast_subagent", request, "low", {})
    gem._atomic_write(cache, text)
    before = cache.read_bytes()
    for _ in range(2):
        result = gem.ask_with_receipt("fast_subagent", request, thinking="low", feature="roundtrip")
        assert result.text == text
        assert result.receipt["source"] == "cache"
        assert result.receipt["mode"] == "replay"
        assert result.receipt["outcome"] == "ok"
        assert result.receipt["live_attempts"] == 0
        assert result.receipt["attempts"] == []
    assert cache.read_bytes() == before
