"""Tests for voice lane startup and bus integration."""

import asyncio

import voice


def test_voice_start_subscribes():
    class FakeBus:
        def __init__(self):
            self.subscribers = {}

        def subscribe(self, topic, handler):
            self.subscribers[topic] = handler

    bus = FakeBus()
    info = asyncio.run(voice.start(bus))
    assert info["status"] == "ready"
    assert info["demo_language"] == "tr"
    assert "say" in bus.subscribers
    assert callable(bus.subscribers["say"])


def test_say_runs_off_the_event_loop(monkeypatch):
    """The hub awaits the say callback; the slow TTS work must run in a worker thread."""
    import threading

    from voice import speak

    seen = {}

    def fake_handle_say(data):
        seen["thread"] = threading.current_thread()
        seen["data"] = data

    monkeypatch.setattr(speak, "handle_say", fake_handle_say)

    class FakeBus:
        def __init__(self):
            self.subscribers = {}

        def subscribe(self, topic, handler):
            self.subscribers[topic] = handler

    async def run():
        bus = FakeBus()
        await voice.start(bus)
        await bus.subscribers["say"]({"to": "operator", "text": "hi"})

    asyncio.run(run())
    assert seen["data"]["text"] == "hi"
    assert seen["thread"] is not threading.main_thread()
