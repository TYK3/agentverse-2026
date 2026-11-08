"""SPEAK-PLAY: synthesised TTS audio is actually played (sd.play + sd.wait on 24 kHz 16-bit PCM), and
playback is skipped, not crashed, when there is no audio output device. sounddevice is mocked."""

import struct
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from voice import speak

PCM = struct.pack("<4h", 0, 1000, -1000, 32767)          # 4 samples, 8 bytes


def _sd(no_device=False, play_error=None):
    sd = MagicMock()
    if no_device:
        sd.query_devices.side_effect = Exception("Error querying device -1")
    if play_error:
        sd.play.side_effect = play_error
    return sd


@contextmanager
def _live_tts(audio):
    part = MagicMock()
    part.inline_data.data = audio
    response = MagicMock(candidates=[MagicMock(content=MagicMock(parts=[part]))])
    gem = MagicMock(MODEL_IDS={"tts_studio": "gemini-3.8-flash-tts"})
    gem._c.return_value.models.generate_content.return_value = response
    with patch.dict("sys.modules", {"coord": MagicMock(gem=gem)}):
        yield gem


def _samples(arg):
    return [int(v) for v in arg]


def test_play_pcm_plays_24khz_int16_and_waits():
    sd = _sd()
    with patch.dict("sys.modules", {"sounddevice": sd}):
        assert speak._play_pcm(PCM) == (True, "played")
    sd.query_devices.assert_called_once_with(kind="output")
    (samples,), kwargs = sd.play.call_args
    assert _samples(samples) == [0, 1000, -1000, 32767]
    assert kwargs == {"samplerate": 24000}
    sd.wait.assert_called_once_with()
    assert [c[0] for c in sd.method_calls] == ["query_devices", "play", "wait"]


def test_play_pcm_skips_without_an_output_device():
    sd = _sd(no_device=True)
    with patch.dict("sys.modules", {"sounddevice": sd}):
        played, why = speak._play_pcm(PCM)
    assert not played and why.startswith("no audio output device")
    sd.play.assert_not_called()
    sd.wait.assert_not_called()


def test_play_pcm_skips_without_sounddevice():
    with patch.dict("sys.modules", {"sounddevice": None}):   # import raises ImportError
        played, why = speak._play_pcm(PCM)
    assert not played and why.startswith("sounddevice unavailable")


def test_play_pcm_drops_a_trailing_odd_byte_and_skips_empty_audio():
    sd = _sd()
    with patch.dict("sys.modules", {"sounddevice": sd}):
        assert speak._play_pcm(PCM + b"\x01")[0]
        assert _samples(sd.play.call_args[0][0]) == [0, 1000, -1000, 32767]
        assert speak._play_pcm(b"\x01") == (False, "empty audio")


def test_play_error_mid_playback_is_reported_not_raised():
    sd = _sd(play_error=Exception("device unplugged"))
    with patch.dict("sys.modules", {"sounddevice": sd}):
        played, why = speak._play_pcm(PCM)
    assert not played and "device unplugged" in why


def test_speak_text_live_plays_the_audio(monkeypatch):
    monkeypatch.setenv("GEMINI_MODE", "live")
    sd = _sd()
    with _live_tts(PCM), patch.dict("sys.modules", {"sounddevice": sd}):
        res = speak.speak_text("Help is coming", to="casualty")
    assert res == {"spoken": True, "mode": "audio", "bytes": len(PCM), "text": "Help is coming"}
    sd.play.assert_called_once()
    sd.wait.assert_called_once()


def test_speak_text_live_without_a_device_keeps_the_audio_unplayed(monkeypatch):
    monkeypatch.setenv("GEMINI_MODE", "live")
    sd = _sd(no_device=True)
    with _live_tts(PCM) as gem, patch.dict("sys.modules", {"sounddevice": sd}):
        res = speak.speak_text("Help is coming", to="casualty")
    assert res["mode"] == "audio_synthesised" and res["spoken"] is True and res["bytes"] == len(PCM)
    sd.play.assert_not_called()
    gem.mark_stand_in.assert_called_with("tts")
