"""T21 checks: change-of-mind resolution, the typed twin, the live reply handler and the transcript.
No key, network, microphone or google-genai needed (GEMINI_MODE=off)."""

import asyncio
import io
import json

import pytest

from voice import command, operator, typed
from voice import intent as intents


class FakeBus:
    def __init__(self):
        self.sent = []

    async def publish(self, topic, data):
        self.sent.append((topic, data))


@pytest.fixture
def log_path(tmp_path):
    return tmp_path / "transcript.jsonl"


@pytest.mark.parametrize("said, intent, text", [
    ("send water to the left room, no, the back room",
     {"goal": "deliver", "item": "water", "place": "back room"}, "send water to the back room"),
    ("Bring the first aid kit to the kitchen.",
     {"goal": "deliver", "item": "first_aid_kit", "place": "kitchen"}, "send the first aid kit to the kitchen"),
    ("scan the stairwell", {"goal": "scan", "item": None, "place": "stairwell"}, "scan the stairwell"),
    ("send the radio to the hall, sorry, I mean the water",
     {"goal": "deliver", "item": "water", "place": "hall"}, "send water to the hall"),
    ("send water to the left room no wait to the back room",
     {"goal": "deliver", "item": "water", "place": "back room"}, "send water to the back room"),
    ("send water to the left room, actually, stop", {"goal": "stop", "item": None, "place": None}, "stop"),
    ("check the left room, no, send water there instead to the corridor",
     {"goal": "deliver", "item": "water", "place": "corridor"}, "send water to the corridor"),
    ("come back", {"goal": "return", "item": None, "place": None}, "return to base"),
])
def test_parse_resolves_change_of_mind(said, intent, text):
    assert intents.parse(said) == intent
    assert intents.to_text(intent) == text


@pytest.mark.parametrize("said", ["", "hello there", "send water", "no"])
def test_incomplete_is_not_a_command(said):
    assert intents.to_text(intents.parse(said)) is None


def test_typed_twin_three_commands_one_change_of_mind(log_path):
    bus = FakeBus()
    lines = ["send water to the left room, no, the back room\n", "scan the kitchen\n", "\n",
             "bring the radio to the hall\n", "blah\n"]
    asyncio.run(typed.run(bus, lines, log_path))
    assert bus.sent == [
        ("operator/command", {"text": "send water to the back room", "source": "typed"}),
        ("operator/command", {"text": "scan the kitchen", "source": "typed"}),
        ("operator/command", {"text": "send the radio to the hall", "source": "typed"}),
    ]
    log = [json.loads(x) for x in log_path.read_text().splitlines()]
    assert [e["heard"] for e in log] == ["send water to the left room, no, the back room", "scan the kitchen",
                                         "bring the radio to the hall", "blah"]
    assert log[-1]["published"] is None and all("t" in e for e in log)


@pytest.mark.parametrize("reply", [
    '{"goal": "deliver", "item": "water", "place": "Back Room"}',
    '```json\n{"goal":"deliver","item":"water","place":"back room"}\n```',
])
def test_live_reply_becomes_voice_command(reply, log_path):
    bus = FakeBus()
    heard = "send water to the left room, no, the back room"
    msg = asyncio.run(operator.handle_reply(bus, reply, heard, log_path))
    assert msg == {"text": "send water to the back room", "source": "voice"}
    assert bus.sent == [("operator/command", msg)]
    entry = json.loads(log_path.read_text())
    assert entry["heard"] == heard and entry["resolved_by"] == operator.model_id()


def test_unusable_live_reply_falls_back_to_transcript_and_says_so(log_path):
    bus = FakeBus()
    msg = asyncio.run(operator.handle_reply(bus, "sorry?", "scan the left room, no, the back room", log_path))
    assert msg == {"text": "scan the back room", "source": "voice"}
    assert json.loads(log_path.read_text())["resolved_by"] == "local parser on live transcript"


def test_unclear_live_reply_publishes_nothing(log_path):
    bus = FakeBus()
    assert asyncio.run(operator.handle_reply(bus, '{"goal": null, "item": null, "place": null}', "mm", log_path)) is None
    assert bus.sent == []


def test_off_mode_is_a_labelled_stand_in_using_the_typed_twin(monkeypatch, log_path, capsys):
    monkeypatch.setenv("GEMINI_MODE", "off")
    monkeypatch.setattr(command, "LOG", log_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("send water to the back room\n"))
    bus = FakeBus()
    asyncio.run(operator.run(bus))
    assert "[STAND-IN]" in capsys.readouterr().err
    assert bus.sent == [("operator/command", {"text": "send water to the back room", "source": "typed"})]
    assert json.loads(log_path.read_text().splitlines()[0])["stand_in"] is True


def test_stdout_bus_prints_one_line():
    out = io.StringIO()
    asyncio.run(command.StdoutBus(out).publish("operator/command", {"text": "stop", "source": "typed"}))
    assert out.getvalue() == 'operator/command {"text": "stop", "source": "typed"}\n'
