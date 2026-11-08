"""Tests for speech output (TTS) module (T22).

Validates:
1. In GEMINI_MODE=off, speak falls back to text-only output.
2. Incoming 'say' messages to operator and casualty are handled properly.
3. 'say' to casualty translates into Turkish or displays stand-in notice.
4. Missing sound hardware does not crash the system.
"""

import base64
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

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


class _GeminiOff(Exception):
    pass


def _fake_gem(tmp_path, mode="live", audio=b"\x01\x00\x02\x00\x03\x00", fail=None):
    """A stand-in for coord.gem plus google.genai, returning `audio` as the TTS part."""
    part = MagicMock()
    part.inline_data.data = audio
    response = MagicMock()
    response.candidates = [MagicMock(content=MagicMock(parts=[part]))]
    client = MagicMock()
    if fail:
        client.models.generate_content.side_effect = fail
    else:
        client.models.generate_content.return_value = response
    gem = types.SimpleNamespace(
        MODE=mode, CACHE=tmp_path, MODEL_IDS={"tts_studio": "gemini-3.8-flash-tts"},
        GeminiOff=_GeminiOff, _c=lambda: client, count_call=MagicMock(), mark_stand_in=MagicMock(),
    )
    genai = MagicMock()
    google = MagicMock(genai=genai)
    modules = {"coord": types.SimpleNamespace(gem=gem), "coord.gem": gem,
               "google": google, "google.genai": genai, "google.genai.types": genai.types}
    return gem, client, modules


def _fake_sd():
    sd = MagicMock()
    sd.default = MagicMock()
    return sd


def test_say_is_played_through_sounddevice(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_MODE", "live")
    gem, client, modules = _fake_gem(tmp_path)
    sd = _fake_sd()
    with patch.dict("sys.modules", {**modules, "sounddevice": sd}):
        res = speak.speak_text("Help is coming.", to="casualty")
    assert res == {"spoken": True, "mode": "audio", "bytes": 6, "text": "Help is coming."}
    samples, rate = sd.play.call_args.args
    assert rate == speak.SAMPLE_RATE == 24000
    assert samples.dtype == np.int16 and samples.tolist() == [1, 2, 3]
    sd.wait.assert_called_once()
    gem.count_call.assert_called_once_with("tts")
    kwargs = client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-3.8-flash-tts" and kwargs["contents"] == "Help is coming."
    assert "config" in kwargs  # asks for AUDIO output with a prebuilt voice


def test_replay_reuses_cached_audio(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_MODE", "replay")
    gem, client, modules = _fake_gem(tmp_path, mode="replay")
    with patch.dict("sys.modules", modules):
        assert speak.synthesise("Stay still.") == b"\x01\x00\x02\x00\x03\x00"
        assert speak.synthesise("Stay still.") == b"\x01\x00\x02\x00\x03\x00"
    assert client.models.generate_content.call_count == 1
    assert gem.count_call.call_count == 1


def test_base64_audio_is_decoded(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_MODE", "live")
    _, _, modules = _fake_gem(tmp_path, audio=base64.b64encode(b"\x05\x00").decode())
    with patch.dict("sys.modules", modules):
        assert speak.synthesise("Hi") == b"\x05\x00"


def test_sounddevice_error_falls_back_gracefully(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GEMINI_MODE", "live")
    _, _, modules = _fake_gem(tmp_path)
    sd = _fake_sd()
    sd.play.side_effect = OSError("no default output device")
    with patch.dict("sys.modules", {**modules, "sounddevice": sd}):
        res = speak.speak_text("Sample speech", to="operator")
    assert res["spoken"] is False and res["reason"] == "no_device" and res["bytes"] == 6
    assert "[voice/tts: no device] (operator) Sample speech" in capsys.readouterr().out


def test_synthesise_only_without_device(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_MODE", "live")
    _, _, modules = _fake_gem(tmp_path)
    sd = _fake_sd()
    with patch.dict("sys.modules", {**modules, "sounddevice": sd}):
        res = speak.speak_text("Sample speech", to="operator", allow_device=False)
    assert res["mode"] == "audio_synthesised" and res["bytes"] == 6
    sd.play.assert_not_called()


def test_gem_off_with_live_env_falls_back(monkeypatch, tmp_path, capsys):
    """GEMINI_MODE=live in the env but gem.MODE is off: GeminiOff must not escape."""
    monkeypatch.setenv("GEMINI_MODE", "live")
    _, client, modules = _fake_gem(tmp_path, mode="off")
    with patch.dict("sys.modules", modules):
        res = speak.speak_text("Help is coming.", to="casualty")
    assert res["reason"] == "tts_fallback"
    client.models.generate_content.assert_not_called()
    assert "[voice/tts: fallback]" in capsys.readouterr().out


def test_network_error_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_MODE", "live")
    _, _, modules = _fake_gem(tmp_path, fail=ConnectionError("503 unavailable"))
    with patch.dict("sys.modules", modules):
        res = speak.speak_text("Help is coming.")
    assert res["spoken"] is False and "503" in res["error"]


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


def _wav(frames: bytes, rate: int = 24000) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(frames)
    return buf.getvalue()


def test_wav_from_tts_is_played_without_its_header(monkeypatch, tmp_path):
    """The live TTS returns audio/wav (#76 live test); the RIFF header must not be played as samples."""
    monkeypatch.setenv("GEMINI_MODE", "live")
    _, _, modules = _fake_gem(tmp_path, audio=_wav(b"\x01\x00\x02\x00\x03\x00"))
    sd = _fake_sd()
    with patch.dict("sys.modules", {**modules, "sounddevice": sd}):
        res = speak.speak_text("Help is coming.")
    assert res["spoken"] is True
    samples, rate = sd.play.call_args.args
    assert samples.tolist() == [1, 2, 3] and rate == 24000


def test_decode_raw_pcm_and_rejects_8_bit_wav():
    assert speak.decode(b"\x01\x00\x02") == (b"\x01\x00", 24000, 1)
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(1)
        wf.setframerate(8000)
        wf.writeframes(b"\x80\x80")
    with pytest.raises(ValueError):
        speak.decode(buf.getvalue())
