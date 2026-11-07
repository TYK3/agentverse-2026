"""sim lane: the MuJoCo world. The hub (coord/hub.py) calls `start(bus)` on startup."""

from sim import scene


async def start(bus):
    """Load the backup scene and publish scene/loaded on the bus."""
    m, d = scene.load()
    await bus.publish("scene/loaded", scene.scene_loaded(m, d))
    return m, d
