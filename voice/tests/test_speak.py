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


class _ApiError(Exception):
    """Stands in for google.genai errors, which do not subclass RuntimeError/ValueError/OSError."""

    def __init__(self, code, message):
        super().__init__(f"{code} {message}")
        self.code = code


def _fake_gem_raising(exc):
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = exc
    fake_gem = MagicMock()
    fake_gem._c.return_value = fake_client
    fake_gem.MODEL_IDS = {"tts_studio": "gemini-missing-tts"}
    fake_gem.ask.side_effect = exc
    return fake_gem, fake_client


def test_missing_tts_model_falls_back_and_stops_calling(monkeypatch):
    # ref TTS-FALLBACK: a 404 from the API used to escape and crash the `say` subscriber.
    monkeypatch.setenv("GEMINI_MODE", "live")
    monkeypatch.setattr(speak, "_tts_model_missing", None)
    fake_gem, fake_client = _fake_gem_raising(_ApiError(404, "NOT_FOUND model"))
    with patch.dict("sys.modules", {"coord": MagicMock(gem=fake_gem)}):
        first = speak.speak_text("Help is coming", to="casualty", allow_device=False)
        second = speak.speak_text("Stay where you are", to="casualty", allow_device=False)
    assert first["mode"] == second["mode"] == "text-only"
    assert first["reason"] == "tts_fallback"
    assert fake_client.models.generate_content.call_count == 1


def test_other_tts_api_error_falls_back_and_retries_next_line(monkeypatch):
    monkeypatch.setenv("GEMINI_MODE", "live")
    monkeypatch.setattr(speak, "_tts_model_missing", None)
    fake_gem, fake_client = _fake_gem_raising(_ApiError(503, "UNAVAILABLE"))
    with patch.dict("sys.modules", {"coord": MagicMock(gem=fake_gem)}):
        speak.speak_text("one", allow_device=False)
        res = speak.speak_text("two", allow_device=False)
    assert res["mode"] == "text-only"
    assert fake_client.models.generate_content.call_count == 2


def test_translation_api_error_does_not_crash_say(monkeypatch):
    monkeypatch.setenv("GEMINI_MODE", "live")
    monkeypatch.setattr(speak, "_tts_model_missing", None)
    fake_gem, _ = _fake_gem_raising(_ApiError(404, "NOT_FOUND model"))
    with patch.dict("sys.modules", {"coord": MagicMock(gem=fake_gem)}):
        result = speak.handle_say({"to": "casualty", "intent": "reassure", "text": "Help is coming."})
    assert result["translated_text"] == translate.OFF_STAND_IN_TEXT
    assert result["mode"] == "text-only"


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
