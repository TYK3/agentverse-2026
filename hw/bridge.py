"""The one bridge (Y10 part 2): robot data reaches the hub the same way from the sim or a real robot.

Every message is a contract envelope `{"topic": ..., "data": ...}` on bridge topic
`aftershock/<contract topic>` (for example `aftershock/sensors/scout`). A source (the sim's driver
stack, or a real robot's drivers) publishes to the bridge; the hub side subscribes to the bridge and
republishes into the bus, validated against coord/messages.py. Outside software talks to the bridge
only, never to the sim.

Transports:
- `LoopbackTransport`: in-process, for tests and a single-process demo.
- `MqttTransport`: an MQTT broker (paho-mqtt), for a real robot on the network:
  `AFTERSHOCK_BRIDGE=mqtt://host:1883`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("hw.bridge")

PREFIX = "aftershock/"
ROBOT_TOPICS = ("sensors/scout",)  # topics a robot source may publish into the hub


def bridge_topic(topic: str) -> str:
    return PREFIX + topic


class LoopbackTransport:
    """In-process transport with the same interface as MqttTransport."""

    def __init__(self) -> None:
        self.subs: dict[str, list[Callable[[str, bytes], None]]] = defaultdict(list)

    def publish(self, topic: str, payload: bytes) -> None:
        for pattern, fns in list(self.subs.items()):
            if _match(pattern, topic):
                for fn in list(fns):
                    fn(topic, payload)

    def subscribe(self, pattern: str, fn: Callable[[str, bytes], None]) -> None:
        self.subs[pattern].append(fn)

    def close(self) -> None:
        self.subs.clear()


class MqttTransport:
    """MQTT over paho-mqtt 2.x. Callbacks run on paho's network thread."""

    def __init__(self, host: str, port: int = 1883, client_id: str = "") -> None:
        import paho.mqtt.client as mqtt

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self.handlers: list[tuple[str, Callable[[str, bytes], None]]] = []
        self.client.on_message = lambda _c, _u, msg: [fn(msg.topic, msg.payload) for p, fn in self.handlers
                                                      if _match(p, msg.topic)]
        self.client.connect(host, port)
        self.client.loop_start()

    def publish(self, topic: str, payload: bytes) -> None:
        self.client.publish(topic, payload, qos=0)

    def subscribe(self, pattern: str, fn: Callable[[str, bytes], None]) -> None:
        self.handlers.append((pattern, fn))
        self.client.subscribe(pattern)

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


def _match(pattern: str, topic: str) -> bool:
    """MQTT wildcard match: `+` is one level, a trailing `#` is the rest."""
    p, t = pattern.split("/"), topic.split("/")
    for i, part in enumerate(p):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(p) == len(t)


def from_env(url: str | None = None) -> Any:
    """Transport for AFTERSHOCK_BRIDGE: unset or 'loopback' -> loopback, 'mqtt://host:port' -> MQTT."""
    url = url if url is not None else os.environ.get("AFTERSHOCK_BRIDGE", "loopback")
    if url in ("", "loopback"):
        return LoopbackTransport()
    u = urlparse(url)
    if u.scheme != "mqtt" or not u.hostname:
        raise ValueError(f"AFTERSHOCK_BRIDGE must be 'loopback' or mqtt://host:port, got {url!r}")
    return MqttTransport(u.hostname, u.port or 1883)


class RobotSource:
    """What a robot (simulated or real) uses to send its data. `source` is 'sim' or the robot's name."""

    def __init__(self, transport: Any, source: str = "sim") -> None:
        self.transport = transport
        self.source = source

    def send(self, topic: str, data: Any) -> None:
        if topic not in ROBOT_TOPICS:
            raise ValueError(f"robots publish only {ROBOT_TOPICS}, not {topic}")
        self.transport.publish(bridge_topic(topic), json.dumps({"topic": topic, "data": data}).encode())


class HubLink:
    """The hub side: bridge messages in, validated bus.publish out (on the hub's event loop)."""

    def __init__(self, transport: Any, bus: Any, loop: asyncio.AbstractEventLoop | None = None,
                 validate: Callable[[str, Any], Any] | None = None) -> None:
        self.transport, self.bus = transport, bus
        self.loop = loop or asyncio.get_running_loop()
        self.validate = validate
        self.received = 0
        self.rejected = 0
        transport.subscribe(PREFIX + "#", self._on_message)

    def _on_message(self, topic: str, payload: bytes) -> None:
        try:
            env = json.loads(payload)
            name = env["topic"]
            if bridge_topic(name) != topic or name not in ROBOT_TOPICS or set(env) != {"topic", "data"}:
                raise ValueError(f"bad envelope on {topic}")
            data = self.validate(name, env["data"]) if self.validate else env["data"]
        except (ValueError, KeyError, TypeError) as exc:
            self.rejected += 1
            log.warning("bridge rejected a message on %s: %s", topic, exc)
            return
        self.received += 1
        coro = self.bus.publish(name, data)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self.loop.create_task(coro)
        else:  # paho's network thread
            asyncio.run_coroutine_threadsafe(coro, self.loop)
