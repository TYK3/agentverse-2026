"""Metrics from observed trial traces; no route command counts as observed arrival."""

import math
from dataclasses import asdict, dataclass


@dataclass
class Metrics:
    seed: int
    planner: str
    reached_casualty: bool | None
    unsafe_cells_entered: int | None
    time_to_casualty_s: float | None
    replans: int
    human_approvals: int
    safe_success: bool | None
    completed: bool
    backend: str
    stand_ins: str
    scenario_sha256: str
    error: str = ""

    def row(self):
        return asdict(self)


def measure(trace):
    """Collapse/position ties count as unsafe in either observation order.

    Events use simulation seconds. A `position` event observes one occupied cell;
    a `collapsed` event observes cells that have become unsafe. A cell counts once
    if entered after collapse, or occupied when it collapses. Future collapse of a
    previously visited and vacated cell does not retroactively count as an entry.
    A `reached` command alone is insufficient: the observed position must be the goal.
    """
    collapsed, unsafe, route_ids, approvals = set(), set(), set(), set()
    position = None
    arrival = None
    previous_t = -math.inf
    positions_at_t = set()
    for event in trace["events"]:
        t = event["t"]
        if not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0 or t < previous_t:
            raise ValueError("trace times must be finite, nonnegative and ordered")
        if t != previous_t:
            positions_at_t.clear()
        previous_t = t
        kind = event["kind"]
        if kind == "position":
            position = tuple(event["cell"])
            positions_at_t.add(position)
            if position in collapsed:
                unsafe.add(position)
            if position == tuple(trace["goal"]) and arrival is None:
                arrival = t
        elif kind == "collapsed":
            newly = {tuple(c) for c in event["cells"]}
            collapsed |= newly
            unsafe |= newly & (positions_at_t | ({position} if position is not None else set()))
        elif kind == "route":
            route_ids.add(event["id"])
        elif kind == "approval" and event["approved"]:
            approvals.add(event["id"])

    completed = bool(trace.get("completed")) and position is not None
    reached = arrival is not None if completed else None
    return Metrics(
        seed=trace["seed"], planner=trace["planner"], reached_casualty=reached,
        unsafe_cells_entered=len(unsafe) if completed else None,
        time_to_casualty_s=arrival if completed else None,
        replans=max(0, len(route_ids) - 1), human_approvals=len(approvals),
        safe_success=(reached and not unsafe) if completed else None,
        completed=completed, backend=trace["backend"],
        stand_ins=";".join(trace.get("stand_ins", [])),
        scenario_sha256=trace["scenario_sha256"], error=trace.get("error", ""),
    )


def headline(rows, planner):
    selected = [row for row in rows if row.planner == planner]
    measured = [row for row in selected if row.completed]
    safe = sum(bool(row.safe_success) for row in measured)
    return {"planner": planner, "safe_successes": safe, "measured_trials": len(measured),
            "attempted_trials": len(selected),
            "safe_success_rate": safe / len(measured) if measured else None}
