"""Simulated hardware layer (Y10 part 2). See docs/electronics.md for the parts.

    AFTERSHOCK_HW=1        sim sensors go through the driver stubs (hw/drivers.py) and the bridge
                           (hw/bridge.py) before they reach the hub; unset keeps the direct path.
    AFTERSHOCK_BRIDGE=...  'loopback' (default, in-process) or mqtt://host:1883 so a real robot,
                           or any outside software, publishes sensors/scout to the same bridge.
"""

from __future__ import annotations

from typing import Any

from hw import bridge, drivers


class SimRobot:
    """The sim's Scout as a robot: ideal readings in, chip-shaped frames out over the bridge."""

    def __init__(self, transport: Any, seed: int = 0) -> None:
        self.hardware = drivers.ScoutHardware(seed)
        self.source = bridge.RobotSource(transport, "sim")
        self.sent = 0

    def feed(self, ideal: dict[str, Any]) -> None:
        frame = self.hardware.step(ideal)
        if frame is not None:
            self.source.send("sensors/scout", frame)
            self.sent += 1


def attach(bus: Any, transport: Any | None = None, seed: int = 0) -> SimRobot:
    """Hub side link plus the sim robot on one transport. Call from inside the hub's event loop."""
    transport = transport or bridge.from_env()
    robot = SimRobot(transport, seed)
    robot.link = bridge.HubLink(transport, bus)
    return robot
