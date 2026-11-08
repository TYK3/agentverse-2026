"""Local A* on the z=0 map slice; proposals still need a sim physics check."""

from __future__ import annotations

from heapq import heappop, heappush
from math import ceil, hypot, isfinite, sqrt
from typing import Any, Protocol

Cell = tuple[int, int, int]
NEIGHBOURS = tuple(
    (dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy
)
CLEARANCE_M = 0.15
CLEARANCE_COST = 5.0
# X1 predictive hazards: an at_risk cell is a predicted failure, not a wall. Entering one costs as much
# as a 50 m detour, so any real detour wins; a route that still needs one goes to the human gate
# (enter_at_risk). Cells near a predicted failure cost a little extra, so routes keep a margin.
RISK_COST = 50.0
RISK_MARGIN_M = 0.15
RISK_MARGIN_COST = 5.0


class Bus(Protocol):
    def subscribe(self, topic: str, callback: Any) -> None: ...

    async def publish(self, topic: str, data: dict) -> None: ...


def _cell(value: Any) -> Cell:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or any(type(n) is not int for n in value)
    ):
        raise ValueError("cell must contain three integer grid coordinates")
    return tuple(value)


def _distance(a: Cell, b: Cell, res: float) -> float:
    """Octile distance: an admissible heuristic for eight-connected moves."""
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    return res * (max(dx, dy) + (sqrt(2) - 1) * min(dx, dy))


def _clearance_cells(occupied: set[Cell], res: float, metres: float = CLEARANCE_M) -> set[Cell]:
    radius = ceil(metres / res)
    offsets = [
        (dx, dy)
        for dx in range(-radius, radius + 1)
        for dy in range(-radius, radius + 1)
        if hypot(dx, dy) * res <= metres + 1e-12
    ]
    return {(x + dx, y + dy, 0) for x, y, _ in occupied for dx, dy in offsets}


def _neighbours(cell: Cell, safe: set[Cell]):
    x, y, _ = cell
    for dx, dy in NEIGHBOURS:
        other = (x + dx, y + dy, 0)
        if other not in safe:
            continue
        # Both sides of a diagonal must be safe; never cut a blocked corner.
        if dx and dy and ((x + dx, y, 0) not in safe or (x, y + dy, 0) not in safe):
            continue
        yield other, hypot(dx, dy)


def _frontier(
    reachable: set[Cell], records: dict[Cell, dict], blocked: set[Cell], goal: Cell
) -> list[list[int]]:
    """Up to eight unobserved scan targets beside the reachable safe region.

    Unlisted cells inside the ground map bounds are unknown too. Never invent
    targets outside the map or suggest re-scanning a known hazard. These are
    scan targets, not a route authorised for movement.
    """
    ground = [c for c in records if c[2] == 0]
    if not ground:
        return []
    xmin, xmax = min(c[0] for c in ground), max(c[0] for c in ground)
    ymin, ymax = min(c[1] for c in ground), max(c[1] for c in ground)
    targets = set()
    for x, y, _ in reachable:
        for dx, dy in NEIGHBOURS:
            candidate = (x + dx, y + dy, 0)
            if not (xmin <= candidate[0] <= xmax and ymin <= candidate[1] <= ymax):
                continue
            record = records.get(candidate)
            if candidate in blocked or (record and record["occupied"]):
                continue
            if record is None or record["state"] in ("inferred", "unknown"):
                targets.add(candidate)
    return [list(c) for c in sorted(targets, key=lambda c: (_distance(c, goal, 1), c))[:8]]


def _read_map(map_cells: dict) -> tuple[float, dict[Cell, dict]]:
    res = map_cells["res"]
    if isinstance(res, bool) or not isinstance(res, (int, float)) or not isfinite(res) or res <= 0:
        raise ValueError("map resolution must be a positive finite number of metres")
    records = {}
    for record in map_cells["cells"]:
        cell = _cell(record["cell"])
        if cell in records:
            raise ValueError(f"duplicate map cell: {cell}")
        if record["state"] not in ("seen", "inferred", "unknown"):
            raise ValueError("invalid map cell state")
        if type(record["occupied"]) is not bool:
            raise ValueError("occupied must be a boolean")
        records[cell] = record
    return res, records


def find_route(map_cells: dict, hazards: list[dict], start: Cell, goal: Cell) -> dict:
    """Find the least-cost safe route, or request a re-look at the frontier.

    Cost is step length in metres plus 5 per entered cell whose centre is
    within 0.15 m of an occupied ground cell, 50 per entered at-risk cell and
    5 per cell within 0.15 m of one (X1: predicted failures are avoided before
    the aftershock, and entering one goes to the human gate). Missing,
    inferred, unknown, occupied and collapsed cells, and hazards marked
    "blocked" (physics-rejected) or "exclusion" (L5: debris motion sensed
    nearby), are never traversed. The route includes
    both start and goal. No Gemini call or physics claim is made.
    """
    start, goal = _cell(start), _cell(goal)
    res, records = _read_map(map_cells)
    blocked, impassable, risky = set(), set(), set()
    for hazard in hazards:
        cell = _cell(hazard["cell"])
        if hazard["status"] not in ("stable", "at_risk", "collapsed"):
            raise ValueError("invalid hazard status")
        if hazard["status"] != "stable":
            blocked.add(cell)                     # never a re-look target
        if hazard["status"] == "collapsed" or hazard.get("blocked") is True or hazard.get("exclusion") is True:
            impassable.add(cell)                  # collapsed, rejected by the physics check, or a keep-out zone
        elif hazard["status"] == "at_risk":
            risky.add(cell)
    safe = {
        c for c, r in records.items()
        if c[2] == 0 and r["state"] == "seen" and not r["occupied"] and c not in impassable
    }
    failure = {"status": "no_verified_route", "needs": "re-look", "cells": []}
    if start not in safe or goal[2] != 0:
        return failure

    occupied = {c for c, r in records.items() if c[2] == 0 and r["occupied"]}
    clearance = _clearance_cells(occupied, res)
    margin = _clearance_cells(risky, res, RISK_MARGIN_M) - risky
    costs = {start: 0.0}
    parents: dict[Cell, Cell] = {}
    queue = [(_distance(start, goal, res), 0.0, start)]
    reachable = set()
    while queue:
        _, cost, current = heappop(queue)
        if current in reachable or cost > costs[current]:
            continue
        reachable.add(current)
        if current == goal:
            path = [current]
            while path[-1] != start:
                path.append(parents[path[-1]])
            return {"status": "ok", "cells": [list(c) for c in reversed(path)], "cost": cost}
        for other, step in _neighbours(current, safe):
            candidate_cost = (cost + step * res + (CLEARANCE_COST if other in clearance else 0)
                              + (RISK_COST if other in risky else RISK_MARGIN_COST if other in margin else 0))
            if candidate_cost < costs.get(other, float("inf")):
                costs[other] = candidate_cost
                parents[other] = current
                heappush(queue, (candidate_cost + _distance(other, goal, res), candidate_cost, other))
    failure["cells"] = _frontier(reachable, records, blocked, goal)
    return failure


class RoutePlanner:
    """Latest perception snapshots and publication of local route proposals.

    The caller supplies grid start/goal; pose and intent handling are outside
    T12. Failed searches never publish route/proposed.
    """

    def __init__(self, bus: Bus):
        self.bus = bus
        self.map_cells: dict | None = None
        self.hazards: list[dict] = []
        self._route_number = 0

    def update_map(self, data: dict) -> None:
        # Perception sends deltas between full snapshots. Unlisted cells
        # keep their last observation; an explicit unknown revokes safety.
        res, changes = _read_map(data)
        previous = {}
        if self.map_cells is not None and self.map_cells["res"] == res:
            _, previous = _read_map(self.map_cells)
        previous.update(changes)
        self.map_cells = {**data, "cells": [
            {**record, "cell": list(cell)} for cell, record in previous.items()
        ]}

    def update_hazards(self, data: list[dict]) -> None:
        self.hazards = data

    async def propose(
        self, start: Cell, goal: Cell, *, goal_text: str = "deliver water to c1", publish: bool = True
    ) -> dict:
        if self.map_cells is None:
            return {"status": "no_verified_route", "needs": "re-look", "cells": []}
        result = find_route(self.map_cells, self.hazards, start, goal)
        if result["status"] == "ok":
            self._route_number += 1
            proposal = {
                "id": f"r{self._route_number}",
                "robot": "responder",
                "cells": result["cells"],
                "goal": goal_text,
                "model": "local-astar",
            }
            if publish:
                await self.bus.publish("route/proposed", proposal)
            return {**result, "proposal": proposal}
        return result
