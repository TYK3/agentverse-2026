"""Speech output (TTS) module for AFTERSHOCK.

Subscribes to 'say' messages. Synthesises speech with gemini-3.8-flash-tts
and plays through sounddevice. If GEMINI_MODE=off or if TTS fails,
falls back safely to text-only display.
"""

from __future__ import annotations

import logging
import os
import sys
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


def _count_call() -> None:
    try:
        from coord import gem
        gem.count_call("tts")
    except (ImportError, AttributeError, RuntimeError):
        pass


SAMPLE_RATE = 24000  # Gemini TTS returns 16-bit mono PCM at 24 kHz


def _play_pcm(audio: bytes) -> tuple[bool, str]:
    """Play 16-bit mono PCM at SAMPLE_RATE and wait until it ends (SPEAK-PLAY).

    Returns (played, reason). Skips without raising when sounddevice is missing or there is no output
    device (CI, a headless box), so the caller falls back to text.
    """
    try:
        import sounddevice as sd
    except (ImportError, OSError) as exc:          # OSError: PortAudio library missing
        return False, f"sounddevice unavailable: {exc}"
    try:
        sd.query_devices(kind="output")             # raises when there is no default output device
    except Exception as exc:  # noqa: BLE001 - PortAudioError is a bare Exception subclass
        return False, f"no audio output device: {exc}"
    usable = len(audio) - len(audio) % 2
    if not usable:
        return False, "empty audio"
    try:
        import numpy as np
        samples: Any = np.frombuffer(audio[:usable], dtype=np.int16)
    except ImportError:
        samples = memoryview(audio[:usable]).cast("h")
    try:
        sd.play(samples, samplerate=SAMPLE_RATE)
        sd.wait()
    except Exception as exc:  # noqa: BLE001 - PortAudioError and device errors mid-play
        return False, f"playback failed: {exc}"
    return True, "played"


def speak_text(text: str, to: str = "operator", allow_device: bool = True) -> dict[str, Any]:
    """Speak text using TTS or fall back to text-only output."""
    mode = get_mode()
    if mode == "off":
        _mark_stand_in()
        sys.stdout.write(f"[voice/tts: off] ({to}) {text}\n")
        sys.stdout.flush()
        return {"spoken": False, "mode": "text-only", "reason": "gemini_off", "text": text}

    # Live or replay TTS attempt
    try:
        _count_call()
        from coord import gem

        audio_bytes = None
        try:
            client = gem._c()
            response = client.models.generate_content(
                model=gem.MODEL_IDS.get("tts_studio", "gemini-3.8-flash-tts"),
                contents=text,
            )
            if hasattr(response, "candidates") and response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        audio_bytes = part.inline_data.data
                        break
        except (AttributeError, RuntimeError, KeyError, TypeError, ValueError, OSError) as e:
            logger.debug("Direct TTS synthesis call note: %s", e)

        if audio_bytes and allow_device:
            played, why = _play_pcm(audio_bytes)
            if played:
                logger.info("Played TTS audio for %s: %d bytes", to, len(audio_bytes))
                return {"spoken": True, "mode": "audio", "bytes": len(audio_bytes), "text": text}
            logger.warning("Sounddevice playback skipped: %s", why)
            _mark_stand_in()

        # If audio bytes generated but device wasn't allowed or failed
        if audio_bytes:
            return {"spoken": True, "mode": "audio_synthesised", "bytes": len(audio_bytes), "text": text}

        # Otherwise fallback to text only
        _mark_stand_in()
        sys.stdout.write(f"[voice/tts: fallback] ({to}) {text}\n")
        sys.stdout.flush()
        return {"spoken": False, "mode": "text-only", "reason": "tts_fallback", "text": text}

    except (ImportError, AttributeError, RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
        _mark_stand_in()
        sys.stdout.write(f"[voice/tts: error fallback] ({to}) {text} ({exc})\n")
        sys.stdout.flush()
        return {"spoken": False, "mode": "text-only", "reason": "tts_exception", "error": str(exc), "text": text}


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

    result = speak_text(text_to_speak, to=to)
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
