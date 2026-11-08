"""Casualty translation module for AFTERSHOCK.

Translates operator messages into the casualty's language (gemini-3.5-live-translate-preview),
and translates the casualty's spoken replies back to English.

Decision: Demo casualty language is Turkish ('tr'), selected for earthquake search-and-rescue
scenarios (e.g. 2023 Turkey-Syria earthquake SAR operations).

In GEMINI_MODE=off:
  Returns '[translation unavailable: gemini off]' and marks stand-in 'live_translate'.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("voice.translate")

# Demo language chosen for AFTERSHOCK search and rescue
DEMO_CASUALTY_LANGUAGE = "tr"
DEMO_CASUALTY_LANGUAGE_NAME = "Turkish"
OFF_STAND_IN_TEXT = "[translation unavailable: gemini off]"

FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures" / "translation_roundtrip.json"

# In-memory lookup for fixture translations
_FIXTURE_EN_TO_TR: dict[str, str] = {}
_FIXTURE_TR_TO_EN: dict[str, str] = {}


def _load_fixtures() -> None:
    if _FIXTURE_EN_TO_TR:
        return
    if FIXTURES_PATH.exists():
        try:
            with FIXTURES_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data.get("pairs", []):
                    en = item.get("english", "").strip().rstrip(".!?").lower()
                    tr = item.get("translated", "").strip().rstrip(".!?").lower()
                    if en and tr:
                        _FIXTURE_EN_TO_TR[en] = item["translated"]
                        _FIXTURE_TR_TO_EN[tr] = item["english"]
        except (OSError, json.JSONDecodeError, KeyError) as err:
            logger.debug("Failed loading translation fixtures: %s", err)


def get_mode() -> str:
    """Return the active GEMINI_MODE (off | replay | live)."""
    return os.environ.get("GEMINI_MODE", "off").lower()


def _mark_stand_in() -> None:
    try:
        from coord import gem
        gem.mark_stand_in("live_translate")
    except (ImportError, AttributeError):
        pass


def translate_to_casualty(
    text: str,
    target_lang: str = DEMO_CASUALTY_LANGUAGE,
    allow_fixture: bool = False,
) -> str:
    """Translate an operator/system message into the casualty's language.

    When GEMINI_MODE=off and allow_fixture is False, returns '[translation unavailable: gemini off]'.
    """
    mode = get_mode()
    if mode == "off" and not allow_fixture:
        _mark_stand_in()
        return OFF_STAND_IN_TEXT

    _load_fixtures()
    normalized = text.strip().rstrip(".!?").lower()
    if allow_fixture and normalized in _FIXTURE_EN_TO_TR:
        return _FIXTURE_EN_TO_TR[normalized]

    # Attempt live or replay call through coord.gem
    try:
        from coord import gem
        prompt = (
            f"You are an emergency rescue translator. Translate the following English rescue message "
            f"directly into {target_lang} for a trapped casualty. Output only the translated text.\n\n"
            f"Message: {text}"
        )
        translated = gem.ask("live_translate", prompt, feature="live_translate")
        return translated.strip()
    except Exception as exc:  # noqa: BLE001 - google-genai API errors are not builtins; fall back, never crash `say`
        logger.debug("Live translation unavailable, using fallback: %s", exc)
        _mark_stand_in()
        if allow_fixture and normalized in _FIXTURE_EN_TO_TR:
            return _FIXTURE_EN_TO_TR[normalized]
        return OFF_STAND_IN_TEXT


def translate_casualty_reply(
    casualty_text: str,
    source_lang: str = DEMO_CASUALTY_LANGUAGE,
    target_lang: str = "en",
    allow_fixture: bool = False,
) -> str:
    """Translate a casualty's reply in their native language back to the operator (English).

    When GEMINI_MODE=off and allow_fixture is False, returns '[translation unavailable: gemini off]'.
    """
    mode = get_mode()
    if mode == "off" and not allow_fixture:
        _mark_stand_in()
        return OFF_STAND_IN_TEXT

    _load_fixtures()
    normalized = casualty_text.strip().rstrip(".!?").lower()
    if allow_fixture and normalized in _FIXTURE_TR_TO_EN:
        return _FIXTURE_TR_TO_EN[normalized]

    # Attempt live or replay call through coord.gem
    try:
        from coord import gem
        prompt = (
            f"You are an emergency rescue translator. Translate the following casualty response "
            f"from {source_lang} into {target_lang} for the rescue operator. Output only the translated text.\n\n"
            f"Casualty response: {casualty_text}"
        )
        translated = gem.ask("live_translate", prompt, feature="live_translate")
        return translated.strip()
    except Exception as exc:  # noqa: BLE001 - google-genai API errors are not builtins; fall back, never crash `say`
        logger.debug("Casualty reply translation unavailable, using fallback: %s", exc)
        _mark_stand_in()
        if allow_fixture and normalized in _FIXTURE_TR_TO_EN:
            return _FIXTURE_TR_TO_EN[normalized]
        return OFF_STAND_IN_TEXT


def round_trip(text: str, allow_fixture: bool = True) -> dict[str, Any]:
    """Perform a round-trip translation: English -> Casualty Lang -> English."""
    casualty_version = translate_to_casualty(text, target_lang=DEMO_CASUALTY_LANGUAGE, allow_fixture=allow_fixture)
    if casualty_version == OFF_STAND_IN_TEXT:
        return {
            "original": text,
            "casualty_version": OFF_STAND_IN_TEXT,
            "round_trip": OFF_STAND_IN_TEXT,
            "success": False,
        }
    back_to_operator = translate_casualty_reply(
        casualty_version,
        source_lang=DEMO_CASUALTY_LANGUAGE,
        target_lang="en",
        allow_fixture=allow_fixture,
    )
    return {
        "original": text,
        "casualty_version": casualty_version,
        "round_trip": back_to_operator,
        "success": bool(back_to_operator and back_to_operator != OFF_STAND_IN_TEXT),
    }
