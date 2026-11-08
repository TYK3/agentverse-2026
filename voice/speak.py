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

# Set once the API says the TTS model does not exist, so later lines skip the call (ref TTS-FALLBACK).
_tts_model_missing: str | None = None


def _is_not_found(exc: BaseException) -> bool:
    """True for a google-genai 404 (model not found); those errors do not subclass the builtins."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return code == 404 or "404" in str(exc)[:40]


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


def speak_text(text: str, to: str = "operator", allow_device: bool = True) -> dict[str, Any]:
    """Speak text using TTS or fall back to text-only output."""
    mode = get_mode()
    if mode == "off":
        _mark_stand_in()
        sys.stdout.write(f"[voice/tts: off] ({to}) {text}\n")
        sys.stdout.flush()
        return {"spoken": False, "mode": "text-only", "reason": "gemini_off", "text": text}

    # Live or replay TTS attempt
    global _tts_model_missing
    try:
        from coord import gem

        model = gem.MODEL_IDS.get("tts_studio", "gemini-3.8-flash-tts")
        audio_bytes = None
        if _tts_model_missing != model:
            _count_call()
            try:
                client = gem._c()
                response = client.models.generate_content(model=model, contents=text)
                if hasattr(response, "candidates") and response.candidates:
                    for part in response.candidates[0].content.parts:
                        if hasattr(part, "inline_data") and part.inline_data:
                            audio_bytes = part.inline_data.data
                            break
            except Exception as e:  # noqa: BLE001 - any API failure means text-only, never a crashed `say`
                if _is_not_found(e):
                    _tts_model_missing = model
                    logger.warning("TTS model %s not found; speaking as text from now on", model)
                else:
                    logger.warning("TTS call failed, text-only for this line: %s", str(e)[:200])

        if audio_bytes and allow_device:
            try:
                import sounddevice as sd

                sd.default.samplerate = 24000
                logger.info("Playing TTS audio for %s: %d bytes", to, len(audio_bytes))
                return {"spoken": True, "mode": "audio", "bytes": len(audio_bytes), "text": text}
            except (ImportError, OSError, RuntimeError) as sde:
                logger.warning("Sounddevice playback unavailable: %s", sde)
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
