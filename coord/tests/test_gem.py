"""T26 checks for coord/gem.py: off never touches the network, replay reads the cache, the cap holds,
and 429/503 are retried. No key and no network are needed."""

import os
import subprocess
import sys
import types

import pytest

from coord import gem


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(gem, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(gem, "_calls", [])
    monkeypatch.setattr(gem, "stand_ins", set())
    monkeypatch.setattr(gem.time, "sleep", lambda s: None)


def fake_client(monkeypatch, replies):
    """Make _c() return a client whose interactions.create pops replies (an Exception is raised)."""
    seen = []

    def create(**kw):
        seen.append(kw)
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return types.SimpleNamespace(output_text=r)

    client = types.SimpleNamespace(interactions=types.SimpleNamespace(create=create))
    monkeypatch.setattr(gem, "_c", lambda: client)
    return seen


def test_off_raises_and_never_imports_genai():
    code = ("import sys; from coord import gem\n"
            "try:\n    gem.ask('fast_subagent', 'hi', feature='vision')\n"
            "except gem.GeminiOff as e:\n    print('off', e)\n"
            "assert 'google.genai' not in sys.modules, 'off mode imported google.genai'\n")
    env = {**os.environ, "GEMINI_MODE": "off"}
    env.pop("GEMINI_API_KEY", None)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out = subprocess.run([sys.executable, "-c", code], check=False, cwd=root, env=env,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "off vision"


def test_off_lets_caller_label_stand_in(monkeypatch):
    monkeypatch.setattr(gem, "MODE", "off")
    with pytest.raises(gem.GeminiOff):
        gem.ask("lead_reasoning", "plan")
    gem.mark_stand_in("route_review")
    assert gem.status() == {"mode": "off", "calls_last_hour": 0, "stand_ins": ["route_review"]}


def test_replay_returns_cache_without_network(monkeypatch):
    monkeypatch.setattr(gem, "MODE", "replay")
    monkeypatch.setattr(gem, "_c", lambda: pytest.fail("replay hit the network on a cached request"))
    f = gem._cache_file("fast_subagent", "is anyone there?", "medium", {})
    f.parent.mkdir(parents=True)
    f.write_text("yes, one person", encoding="utf-8")
    assert gem.ask("fast_subagent", "is anyone there?") == "yes, one person"
    assert gem.status()["calls_last_hour"] == 0


def test_replay_miss_calls_once_then_caches(monkeypatch):
    monkeypatch.setattr(gem, "MODE", "replay")
    seen = fake_client(monkeypatch, ["ready"])
    assert gem.ask("lead_reasoning", "ping", thinking="low") == "ready"
    assert gem.ask("lead_reasoning", "ping", thinking="low") == "ready"
    assert len(seen) == 1
    assert seen[0]["model"] == "gemini-4-argon"
    assert seen[0]["generation_config"] == {"thinking_level": "low"}


def test_cap_raises_when_exceeded(monkeypatch):
    monkeypatch.setattr(gem, "MODE", "live")
    monkeypatch.setattr(gem, "CAP", 2)
    fake_client(monkeypatch, ["a", "b", "c"])
    gem.ask("fast_subagent", "1")
    gem.ask("fast_subagent", "2")
    with pytest.raises(RuntimeError, match="cap reached"):
        gem.ask("fast_subagent", "3")
    assert gem.status()["calls_last_hour"] == 2


def test_count_call_shares_the_cap(monkeypatch):
    monkeypatch.setattr(gem, "CAP", 1)
    gem.count_call("live_voice")
    with pytest.raises(RuntimeError, match="live_voice"):
        gem.count_call("live_voice")


def test_503_is_retried(monkeypatch):
    monkeypatch.setattr(gem, "MODE", "live")
    seen = fake_client(monkeypatch, [RuntimeError("503 UNAVAILABLE"), RuntimeError("429 RESOURCE_EXHAUSTED"), "ok"])
    assert gem.ask("fast_subagent", "frame") == "ok"
    assert len(seen) == 3
    assert gem.status()["calls_last_hour"] == 3  # each real retry consumes the cap


def test_other_errors_are_not_retried(monkeypatch):
    monkeypatch.setattr(gem, "MODE", "live")
    seen = fake_client(monkeypatch, [RuntimeError("400 INVALID_ARGUMENT"), "never"])
    with pytest.raises(RuntimeError, match="400"):
        gem.ask("fast_subagent", "frame")
    assert len(seen) == 1


def test_503_gives_up_after_three_tries(monkeypatch):
    monkeypatch.setattr(gem, "MODE", "live")
    fake_client(monkeypatch, [RuntimeError("503")] * 3)
    with pytest.raises(RuntimeError, match="503"):
        gem.ask("fast_subagent", "frame")
