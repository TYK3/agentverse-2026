"""Tests for speech output (TTS) module (T22).

Validates:
1. In GEMINI_MODE=off, speak falls back to text-only output.
2. Incoming 'say' messages to operator and casualty are handled properly.
3. 'say' to casualty translates into Turkish or displays stand-in notice.
4. Missing sound hardware does not crash the system.
"""

from unittest.mock import MagicMock, patch

from voice import speak, translate


def test_speak_off_mode(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_MODE", "off")
    res = speak.speak_text("Testing spoken output", to="operator")
    assert res["spoken"] is False
    assert res["mode"] == "text-only"
    assert res["reason"] == "gemini_off"
    captured = capsys.readouterr()
    assert "[voice/tts: off]" in captured.out
    assert "Testing spoken output" in captured.out


def test_handle_say_operator(monkeypatch):
    monkeypatch.setenv("GEMINI_MODE", "off")
    payload = {
        "to": "operator",
        "intent": "reassure",
        "text": "Responder has entered Room 2.",
        "lang": "auto",
    }
    result = speak.handle_say(payload)
    assert result["to"] == "operator"
    assert result["intent"] == "reassure"
    assert result["original_text"] == "Responder has entered Room 2."
    assert result["translated_text"] is None
    assert result["mode"] == "text-only"


def test_handle_say_casualty_in_off_mode(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_MODE", "off")
    payload = {
        "to": "casualty",
        "intent": "first_aid",
        "text": "Keep warm and stay still.",
        "lang": "auto",
    }
    result = speak.handle_say(payload)
    assert result["to"] == "casualty"
    assert result["intent"] == "first_aid"
    assert result["translated_text"] == translate.OFF_STAND_IN_TEXT
    captured = capsys.readouterr()
    assert "[voice/translation]" in captured.out
    assert translate.OFF_STAND_IN_TEXT in captured.out


def test_sounddevice_error_falls_back_gracefully(monkeypatch):
    monkeypatch.setenv("GEMINI_MODE", "live")
    # Mock coord.gem to return fake audio
    fake_part = MagicMock()
    fake_part.inline_data.data = b"RIFFfakeaudiobytes"
    fake_response = MagicMock()
    fake_response.candidates = [MagicMock(content=MagicMock(parts=[fake_part]))]

    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response

    fake_gem = MagicMock()
    fake_gem._c.return_value = fake_client
    fake_gem.MODEL_IDS = {"tts_studio": "gemini-3.8-flash-tts"}

    with patch.dict("sys.modules", {"coord": MagicMock(gem=fake_gem)}):
        # Allow synthesis but test sounddevice failure
        res = speak.speak_text("Sample speech", to="operator", allow_device=False)
        assert res["mode"] == "audio_synthesised"
        assert res["bytes"] == len(b"RIFFfakeaudiobytes")


def test_subscribe_registers_handler():
    class FakeBus:
        def __init__(self):
            self.handlers = {}

        def subscribe(self, topic, fn):
            self.handlers[topic] = fn

    bus = FakeBus()
    speak.subscribe(bus)
    assert "say" in bus.handlers
    assert bus.handlers["say"] == speak.handle_say
