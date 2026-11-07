"""Tests for casualty translation module (T22).

Validates:
1. In GEMINI_MODE=off, translation returns '[translation unavailable: gemini off]'.
2. The chosen demo language is Turkish ('tr').
3. Casualty lines round-trip through translation in the chosen language.
4. Fixtures cover essential rescue phrases.
"""

from unittest.mock import patch

from voice import translate


def test_demo_language_is_turkish():
    assert translate.DEMO_CASUALTY_LANGUAGE == "tr"
    assert "Turkish" in translate.DEMO_CASUALTY_LANGUAGE_NAME


def test_gemini_off_returns_stand_in(monkeypatch):
    monkeypatch.setenv("GEMINI_MODE", "off")
    result = translate.translate_to_casualty("Help is on the way, stay calm.")
    assert result == translate.OFF_STAND_IN_TEXT

    reply_result = translate.translate_casualty_reply("Yardım yolda, sakin olun.")
    assert reply_result == translate.OFF_STAND_IN_TEXT


def test_round_trip_with_fixtures():
    original = "Help is on the way, stay calm."
    # With allow_fixture=True, translation can round-trip deterministically
    rt = translate.round_trip(original, allow_fixture=True)
    assert rt["success"] is True
    assert rt["original"] == original
    assert rt["casualty_version"] == "Yardım yolda, sakin olun."
    assert "help" in rt["round_trip"].lower()


def test_casualty_reply_to_operator_fixture():
    casualty_said = "Enkaz altındayım, bacağım sıkıştı."
    operator_hears = translate.translate_casualty_reply(
        casualty_said,
        source_lang="tr",
        target_lang="en",
        allow_fixture=True,
    )
    assert "trapped" in operator_hears.lower() or "rubble" in operator_hears.lower()


def test_round_trip_off_mode_without_fixtures(monkeypatch):
    monkeypatch.setenv("GEMINI_MODE", "off")
    rt = translate.round_trip("Help is on the way, stay calm.", allow_fixture=False)
    assert rt["success"] is False
    assert rt["casualty_version"] == translate.OFF_STAND_IN_TEXT
    assert rt["round_trip"] == translate.OFF_STAND_IN_TEXT


def test_live_translation_calls_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_MODE", "live")

    class FakeGem:
        def __init__(self):
            self.calls = []

        def ask(self, model_key, prompt, feature="?", **kwargs):
            self.calls.append((model_key, prompt, feature))
            if "into tr" in prompt:
                return "Yardım yolda."
            return "Help is coming."

        def mark_stand_in(self, feature):
            pass

    fake_gem = FakeGem()
    with patch.dict("sys.modules", {"coord": type("coord", (), {"gem": fake_gem})}):
        casualty_text = translate.translate_to_casualty("Help is coming.", target_lang="tr", allow_fixture=False)
        assert casualty_text == "Yardım yolda."
        assert len(fake_gem.calls) == 1
        assert fake_gem.calls[0][0] == "live_translate"

        op_text = translate.translate_casualty_reply("Yardım yolda.", source_lang="tr", target_lang="en", allow_fixture=False)
        assert op_text == "Help is coming."
        assert len(fake_gem.calls) == 2
