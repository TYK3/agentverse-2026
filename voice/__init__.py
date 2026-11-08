"""voice lane: talking to the operator and the casualty (T21, T22).

Owns:
- Operator voice commands (T21: voice/operator.py, voice/typed.py, voice/intent.py)
- Spoken guidance (TTS) via gemini-3.8-flash-tts with sounddevice (voice/speak.py)
- Casualty translation via gemini-3.5-live-translate-preview (voice/translate.py)
- Cited first aid guidance steps (voice/firstaid.py, voice/firstaid.json)
- Emergency call report preparation and gate/request publishing (voice/emergency.py)

The hub (coord/hub.py) calls `async def start(bus)` on startup.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from voice import emergency, firstaid, guide, speak, translate

try:
    from voice import intent, operator, typed  # T21 components
except ImportError:
    intent = None  # type: ignore[assignment]
    operator = None  # type: ignore[assignment]
    typed = None  # type: ignore[assignment]


GUIDE: guide.Guide | None = None  # the running guide voice (Y5); Y3/Y6 read GUIDE.summary(cid)
_tasks: set[asyncio.Task] = set()


async def _speak_lines(queue: asyncio.Queue) -> None:
    """Speak guide lines one after another, off the event loop."""
    while True:
        line = await queue.get()
        try:
            await asyncio.to_thread(speak.handle_say, line)
        except Exception:  # noqa: BLE001 - one bad line must not stop the guide
            speak.logger.exception("guide line failed")


def start_guide(bus: Any) -> guide.Guide:
    """Wire the guide voice to the bus. Set VOICE_GUIDE=0 to leave it off."""
    global GUIDE
    g = GUIDE = guide.Guide()
    queue: asyncio.Queue = asyncio.Queue()

    def feed(lines: list[dict[str, Any]]) -> None:
        for line in lines:
            queue.put_nowait(line)

    bus.subscribe("map/cells", lambda d: feed(g.on_cells(d)))
    bus.subscribe("map/casualties", lambda d: feed(g.on_casualties(d, time.monotonic())))
    bus.subscribe("route/proposed", lambda d: feed(g.on_route_proposed(d)))
    bus.subscribe("route/verified", lambda d: feed(g.on_route_verified(d, time.monotonic())))
    bus.subscribe("world/change", lambda d: feed(g.on_world_change(d, time.monotonic())))

    async def ticker() -> None:
        while True:
            await asyncio.sleep(1.0)
            feed(g.tick(time.monotonic()))

    for coro in (_speak_lines(queue), ticker()):
        task = asyncio.get_running_loop().create_task(coro)
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    return g


async def start(bus: Any) -> dict[str, Any]:
    """Start the voice lane: speak planner `say` lines and run the casualty guide voice."""
    # TTS, translation and playback block for seconds, so run them off the hub's event loop.
    async def _on_say(data: dict[str, Any]) -> None:
        await asyncio.to_thread(speak.handle_say, data)

    bus.subscribe("say", _on_say)
    guide_on = os.environ.get("VOICE_GUIDE", "1") != "0"
    if guide_on:
        start_guide(bus)
    return {
        "status": "ready",
        "demo_language": translate.DEMO_CASUALTY_LANGUAGE,
        "firstaid_steps_loaded": len(firstaid.get_steps()),
        "guide": guide_on,
    }


__all__ = [
    "emergency",
    "firstaid",
    "guide",
    "intent",
    "operator",
    "speak",
    "start",
    "translate",
    "typed",
]
