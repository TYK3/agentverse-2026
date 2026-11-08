"""DEMO-FLOW-2/3 checks for tools/demo.py: arguments, the commands it starts, replay staging and URLs,
auto-approve answers and the waits. No processes are started here (CI has no MuJoCo)."""

import json
import sys

import pytest

from tools import demo


def test_defaults_and_validation():
    a = demo.parse([])
    assert (a.scene, a.duration, a.shift_at, a.auto_approve, a.speed, a.replay) == ("backup", 120.0, None, False, 4.0, None)
    a = demo.parse(["--scene", "tower", "--duration", "90", "--shift-at", "45", "--auto-approve"])
    assert (a.scene, a.duration, a.shift_at, a.auto_approve) == ("tower", 90.0, 45.0, True)
    for bad in (["--duration", "0"], ["--speed", "-1"], ["--duration", "30", "--shift-at", "30"]):
        with pytest.raises(SystemExit):
            demo.parse(bad)


def test_hub_command_records_the_run_where_the_console_serves_it():
    record = demo.RUNS / "demo-x.jsonl"
    argv, env = demo.hub_command("building", record, env={"PATH": "p"})
    assert argv[:4] == [sys.executable, "-m", "uvicorn", "coord.hub:app"]
    assert argv[argv.index("--port") + 1] == "8000"                    # where console/src/bus.ts connects
    assert env["SIM_SCENE"] == "building" and env["SIM_RECORD"] == str(record)
    assert env["GEMINI_MODE"] == "off" and env["PATH"] == "p"
    _, env = demo.hub_command("backup", record, env={"GEMINI_MODE": "live"})
    assert env["GEMINI_MODE"] == "live"                                 # an explicit mode is kept
    assert demo.RUNS.parts[-3:] == ("console", "public", "runs")


def test_console_command_and_urls():
    argv = demo.console_command()
    assert argv[1:3] == ["run", "dev"] and "--strictPort" in argv and argv[argv.index("--port") + 1] == "5173"
    assert demo.live_url() == "http://127.0.0.1:5173/"
    assert demo.replay_url("demo-1.jsonl", 4.0) == "http://127.0.0.1:5173/?run=/runs/demo-1.jsonl&speed=4"
    assert demo.replay_url("demo-1.jsonl", 0.5).endswith("&speed=0.5")
    assert demo.run_name("20261108-0300") == "demo-20261108-0300.jsonl"


def test_auto_approve_answers_only_gate_requests():
    req = {"topic": "gate/request", "data": {"id": "g4", "kind": "risky_move", "summary": "s", "route": "r3"}}
    assert demo.answer_for(req) == {"topic": "gate/answer", "data": {"id": "g4", "approved": True, "by": "operator"}}
    assert demo.answer_for({"topic": "gate/decision", "data": {"id": "d1"}}) is None
    assert demo.answer_for({"topic": "gate/request", "data": {}}) is None
    assert demo.answer_for({"topic": "gate/request", "data": "x"}) is None


def test_stage_replay_copies_into_public_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "RUNS", tmp_path / "public" / "runs")
    src = tmp_path / "rescue-1.jsonl"
    src.write_text('{"t":0,"topic":"scene/loaded","data":{"scene":"backup","blocks":[]}}\n', encoding="utf-8")
    assert demo.stage_replay(src) == "rescue-1.jsonl"
    assert (demo.RUNS / "rescue-1.jsonl").read_text(encoding="utf-8") == src.read_text(encoding="utf-8")
    assert demo.stage_replay(demo.RUNS / "rescue-1.jsonl") == "rescue-1.jsonl"   # already there: fine


def test_summarize_counts_topics_and_skips_bad_lines(tmp_path):
    rec = tmp_path / "r.jsonl"
    lines = [{"t": 0, "topic": "scene/loaded", "data": {}}, {"t": 0.1, "topic": "sim/truth", "data": {}},
             {"t": 14.9, "topic": "world/change", "data": {}}]
    rec.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")
    assert demo.summarize(rec) == {"topics": {"scene/loaded": 1, "sim/truth": 1, "world/change": 1}, "t0": 0, "t1": 14.9}


def test_wait_http_retries_until_up_and_gives_up(monkeypatch):
    monkeypatch.setattr(demo.time, "sleep", lambda s: None)
    calls = []

    class Ok:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(url, timeout):
        calls.append(url)
        if len(calls) < 3:
            raise OSError("refused")
        return Ok()

    assert demo.wait_http("http://x", timeout=60, opener=opener) and len(calls) == 3

    def never(url, timeout):
        raise OSError("refused")

    assert demo.wait_http("http://x", timeout=0.01, opener=never) is False


def test_inject_posts_the_aftershock():
    sent = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true}'

    def opener(req, timeout):
        sent.append((req.full_url, req.get_method(), json.loads(req.data)))
        return Resp()

    assert demo.inject_aftershock(opener=opener) == {"ok": True}
    assert sent == [("http://127.0.0.1:8000/inject", "POST", {"kind": "aftershock"})]
