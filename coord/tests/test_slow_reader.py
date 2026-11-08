"""A stalled browser must not hold local subscribers or another browser's replay."""

import asyncio

from coord.hub import Bus


def test_stalled_browser_is_dropped_before_it_blocks_the_bus():
    async def exercise():
        bus = Bus()
        never = asyncio.Event()
        slow = type("SlowBrowser", (), {"send_text": lambda self, _: never.wait()})()
        bus.clients.add(slow)
        local = []
        bus.subscribe("log/decision", local.append)
        data = {"t": 0, "perception": "measured", "model": "off", "physics": "none",
                "outcome": "ready", "reason": "one"}
        await asyncio.wait_for(bus.publish("log/decision", data), timeout=2.0)
        assert local == [data] and slow not in bus.clients

        class Browser:
            def __init__(self):
                self.messages = []

            async def send_text(self, raw):
                self.messages.append(raw)

        healthy = Browser()
        await asyncio.wait_for(bus.connect(healthy), timeout=1.0)
        assert len(healthy.messages) == 1 and '"reason": "one"' in healthy.messages[0]
        data2 = {**data, "reason": "two"}
        await bus.publish("log/decision", data2)
        assert local == [data, data2] and len(healthy.messages) == 2

    asyncio.run(exercise())
