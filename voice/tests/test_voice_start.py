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
