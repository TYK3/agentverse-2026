"""Planner lane: local routing, with physics and human gates added separately."""

from planner.route import RoutePlanner


async def start(bus) -> RoutePlanner:
    """Attach T12 routing to the hub without issuing an automatic movement."""
    planner = RoutePlanner(bus)
    bus.subscribe("map/cells", planner.update_map)
    bus.subscribe("map/hazards", planner.update_hazards)
    return planner
