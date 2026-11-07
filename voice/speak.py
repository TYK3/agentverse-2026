"""Speech output (TTS) module for AFTERSHOCK.

Subscribes to 'say' messages. Synthesises speech with gemini-3.8-flash-tts
and plays through sounddevice. If GEMINI_MODE=off, TTS fails or there is no
sound device, it falls back to printed text and marks the 'tts' stand-in.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sys
import threading
from typing import Any

from voice import translate

logger = logging.getLogger("voice.speak")
logging.basicConfig(level=logging.INFO)


def get_mode() -> str:
    """Return the active GEMINI_MODE (off | replay | live)."""
    return os.environ.get("GEMINI_MODE", "off").lower()


def _mark_stand_in() -> None:
    try:
        from coord import gem
        gem.mark_stand_in("tts")
    except (ImportError, AttributeError):
        pass


SAMPLE_RATE = 24000  # Gemini TTS returns 16-bit mono PCM at 24 kHz
VOICE = os.environ.get("VOICE_TTS_VOICE", "Kore")  # prebuilt voice; calm and clear
CALM_STYLE = "Say this slowly, softly and calmly, like a kind rescuer talking to someone who is scared"
_play_lock = threading.Lock()  # one utterance at a time, so lines never overlap


def _audio_cache_file(gem: Any, text: str) -> Any:
    raw = json.dumps(["tts_studio", VOICE, text])  # text already carries any style prefix
    return gem.CACHE / f"tts-{hashlib.sha256(raw.encode()).hexdigest()}.pcm"


def synthesise(text: str) -> bytes:
    """Return 16-bit PCM for text from gemini-3.8-flash-tts, through coord.gem's client and cap.

    Raises gem.GeminiOff in off mode, or any SDK error; speak_text turns those into text-only.
    In replay mode a cached .pcm in .gem_cache is reused; live calls are cached too.
    """
    from coord import gem

    if gem.MODE == "off":
        raise gem.GeminiOff("tts")
    f = _audio_cache_file(gem, text)
    if gem.MODE == "replay" and f.exists():
        return f.read_bytes()
    gem.count_call("tts")
    from google.genai import types

    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE)
            )
        ),
    )
    response = gem._c().models.generate_content(
        model=gem.MODEL_IDS["tts_studio"], contents=text, config=config
    )
    data = response.candidates[0].content.parts[0].inline_data.data
    if isinstance(data, str):  # some SDK versions hand back base64 text
        data = base64.b64decode(data)
    if not data:
        raise ValueError("tts returned no audio")
    gem.CACHE.mkdir(exist_ok=True)
    f.write_bytes(data)
    return data


def play(pcm: bytes) -> None:
    """Play 16-bit mono PCM on the default output device and wait until it finishes."""
    import numpy as np
    import sounddevice as sd

    samples = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype=np.int16)
    with _play_lock:
        sd.play(samples, SAMPLE_RATE)
        sd.wait()


def _text_only(text: str, to: str, tag: str, reason: str, **extra: Any) -> dict[str, Any]:
    _mark_stand_in()
    sys.stdout.write(f"[voice/tts: {tag}] ({to}) {text}\n")
    sys.stdout.flush()
    return {"spoken": False, "mode": "text-only", "reason": reason, "text": text, **extra}


def speak_text(
    text: str, to: str = "operator", allow_device: bool = True, style: str | None = None
) -> dict[str, Any]:
    """Speak text with Gemini TTS through the sound device; fall back to printed text.

    `style` is a spoken-delivery hint for TTS only (for example CALM_STYLE); it is never printed.
    Never raises: a missing key, the call cap, a network error or no sound device all end
    in text-only output and mark the 'tts' stand-in for the console badge.
    """
    if get_mode() == "off":
        return _text_only(text, to, "off", "gemini_off")
    try:
        pcm = synthesise(f"{style}: {text}" if style else text)
    except Exception as exc:  # noqa: BLE001 - GeminiOff, cap RuntimeError, SDK/network errors
        logger.warning("TTS unavailable, text only: %s", exc)
        return _text_only(text, to, "fallback", "tts_fallback", error=str(exc))
    if not allow_device:
        return {"spoken": False, "mode": "audio_synthesised", "bytes": len(pcm), "text": text}
    try:
        play(pcm)
    except Exception as exc:  # noqa: BLE001 - no numpy/sounddevice/PortAudio/output device
        logger.warning("Sound device unavailable, text only: %s", exc)
        return _text_only(text, to, "no device", "no_device", bytes=len(pcm), error=str(exc))
    logger.info("Spoke %d bytes to %s", len(pcm), to)
    return {"spoken": True, "mode": "audio", "bytes": len(pcm), "text": text}


def handle_say(data: dict[str, Any]) -> dict[str, Any]:
    """Handle an incoming CONTRACT 'say' message.

    Shape: {"to":"casualty"|"operator","intent":"first_aid"|"guide_exit"|"reassure","text":"...","lang":"auto"}
    """
    to = data.get("to", "operator")
    original_text = data.get("text", "")
    intent = data.get("intent", "reassure")
    text_to_speak = original_text

    translated_text = None
    if to == "casualty":
        # Translate to casualty's language (Turkish)
        translated_text = translate.translate_to_casualty(original_text)
        if translated_text == translate.OFF_STAND_IN_TEXT:
            # In off mode: console displays say text and translation shows off notice
            sys.stdout.write(f"[voice/translation] {translate.OFF_STAND_IN_TEXT}\n")
            sys.stdout.flush()
            text_to_speak = original_text
        else:
            text_to_speak = translated_text

    result = speak_text(text_to_speak, to=to, style=CALM_STYLE if to == "casualty" else None)
    result.update({
        "to": to,
        "intent": intent,
        "original_text": original_text,
        "translated_text": translated_text,
    })
    return result


def subscribe(bus: Any) -> None:
    """Subscribe handle_say to 'say' topic on the message bus."""
    bus.subscribe("say", handle_say)
