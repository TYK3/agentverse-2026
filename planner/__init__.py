"""Planner lane: local routing (T12), the verify/gate/re-plan loop (T13) and offline mode (T15)."""

from planner.route import RoutePlanner


async def start(bus) -> RoutePlanner:
    """Attach routing, the T13 loop and the 1 Hz status/budget meter to the hub.

    Returns the router, as before. `router.loop` is the T13 loop (start a mission with
    `await router.loop.mission(start_cell, goal_cell, ...)`); `router.task` is the budget publisher,
    which the hub's lifespan cancels on shutdown. No movement is issued until a mission starts.
    `router.handoff` (X3, planner/handoff.py) starts those missions: each casualty perception reports
    is handed to the Responder, and the work is re-split when the Scout or the Responder is blocked.
    """
    from planner import handoff, loop, permit

    planner = RoutePlanner(bus)
    bus.subscribe("map/cells", planner.update_map)
    bus.subscribe("map/hazards", planner.update_hazards)
    lp = await loop.start(bus, planner)
    planner.loop, planner.task = lp, lp.task
    planner.handoff = handoff.start(bus, lp, planner)
    planner.permits = permit.start(bus)  # L1: move permits that only fresh observation re-earns
    return planner
