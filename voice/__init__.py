"""voice lane: talking to the operator and the casualty (T21, T22).

Owns:
- Operator voice commands (T21: voice/operator.py, voice/typed.py, voice/intent.py)
- Spoken guidance (TTS) via gemini-3.8-flash-tts with sounddevice (voice/speak.py)
- Casualty translation via gemini-3.5-live-translate-preview (voice/translate.py)
- Cited first aid guidance steps (voice/firstaid.py, voice/firstaid.json)
- Emergency call report preparation and gate/request publishing (voice/emergency.py)
- Bounded live casualty contact (G3: voice/contact.py)

The hub (coord/hub.py) calls `async def start(bus)` on startup.
"""

from __future__ import annotations

from typing import Any

from voice import contact, emergency, firstaid, speak, translate

try:
    from voice import intent, operator, typed  # T21 components
except ImportError:
    intent = None  # type: ignore[assignment]
    operator = None  # type: ignore[assignment]
    typed = None  # type: ignore[assignment]


async def start(bus: Any) -> dict[str, Any]:
    """Start the voice lane service, subscribing to relevant topics."""
    # Subscribe to 'say' topic from planner
    def _on_say(data: dict[str, Any]) -> None:
        speak.handle_say(data)

    bus.subscribe("say", _on_say)
    talk = contact.start(bus)  # G3: talks with each located casualty, one at a time
    return {
        "contact": talk,
        "status": "ready",
        "demo_language": translate.DEMO_CASUALTY_LANGUAGE,
        "firstaid_steps_loaded": len(firstaid.get_steps()),
    }


__all__ = [
    "contact",
    "emergency",
    "firstaid",
    "intent",
    "operator",
    "speak",
    "start",
    "translate",
    "typed",
]
