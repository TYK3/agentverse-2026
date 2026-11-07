"""Planner lane: local routing (T12), the verify/gate/re-plan loop (T13) and offline mode (T15)."""

from planner.report import ReportCollector
from planner.route import RoutePlanner


async def start(bus) -> RoutePlanner:
    """Attach routing, the T13 loop and the 1 Hz status/budget meter to the hub.

    Returns the router, as before. `router.loop` is the T13 loop (start a mission with
    `await router.loop.mission(start_cell, goal_cell, ...)`); `router.task` is the budget publisher,
    which the hub's lifespan cancels on shutdown. `router.reporter` collects handover events.
    No movement is issued until a mission starts.
    """
    from planner import loop

    planner = RoutePlanner(bus)
    bus.subscribe("map/cells", planner.update_map)
    bus.subscribe("map/hazards", planner.update_hazards)
    planner.reporter = ReportCollector(bus).attach()
    lp = await loop.start(bus, planner)
    planner.loop, planner.task = lp, lp.task
    return planner
