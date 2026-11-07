"""Scripted T13 run on fixtures: propose, physics fail, re-plan, verify ok, act, aftershock, re-plan.

    python -m planner.loop_run

DEVELOPMENT FIXTURES: the map, the physics answers and the aftershock are scripted here; the routes,
the gate and every log line come from the real loop. No Gemini call unless GEMINI_MODE says so.
"""

import asyncio
import json
import sys

from planner import loop as L
from planner.route import RoutePlanner


class PrintBus:
    def __init__(self):
        self.subs, self.sent = {}, []
        try:
            from coord.messages import (
                validate_payload,  # the hub's schemas (#10), when merged
            )
        except ImportError:
            validate_payload = None
        self.validate = validate_payload

    def subscribe(self, topic, fn):
        self.subs.setdefault(topic, []).append(fn)

    async def publish(self, topic, data):
        if self.validate:
            self.validate(topic, data)
        self.sent.append((topic, data))
        if not topic.startswith("map/"):
            print(json.dumps({"topic": topic, "data": data}))
        for fn in self.subs.get(topic, []):
            r = fn(data)
            if asyncio.iscoroutine(r):
                await r


def room(unknown=()):
    """9 x 7 room, wall at x=4 with gaps at y=1 and y=5, 0.1 m cells."""
    return {"t": 0, "res": 0.1, "cells": [
        {"cell": [x, y, 0], "state": "unknown" if (x, y) in unknown else "seen",
         "occupied": x == 4 and y not in (1, 5) and (x, y) not in unknown}
        for x in range(9) for y in range(7)]}


async def run():
    bus, now = PrintBus(), [0.0]
    router = RoutePlanner(bus)
    bus.subscribe("map/cells", router.update_map)
    lp = L.Loop(bus, router, clock=lambda: now[0]).attach()
    await bus.publish("map/cells", room())
    await bus.publish("map/hazards", [])
    await bus.publish("map/casualties", [{"id": "c1", "pos": [0.85, 0.35, 0], "confidence": 0.9,
                                          "clues": ["thermal", "sound"],
                                          "vitals": {"breathing_rate": 14, "simulated": True}}])
    await lp.mission((0, 3, 0), (8, 3, 0))
    r1 = lp.route
    gap = next(c for c in r1["cells"] if c[0] == 4)
    await bus.publish("route/verified", {"id": r1["id"], "ok": False, "unstable_cells": [gap],
                                         "detail": "block b7 falls"})
    await bus.publish("route/verified", {"id": lp.route["id"], "ok": True, "unstable_cells": [], "detail": ""})
    now[0] = 30.0
    await bus.publish("world/change", {"kind": "aftershock", "t": 30, "moved_blocks": ["b7"]})
    now[0] = 32.0  # perception marks the moved area unknown again: no route over seen cells, re-look
    other = [4, 5, 0] if gap[1] == 1 else [4, 1, 0]
    await bus.publish("map/cells", {"t": 32, "res": 0.1, "cells": [
        {"cell": other, "state": "unknown", "occupied": False}]})
    now[0] = 36.0  # the Scout has re-scanned it: clear floor
    await bus.publish("map/cells", {"t": 36, "res": 0.1, "cells": [
        {"cell": other, "state": "seen", "occupied": False}]})
    topics = [t for t, _ in bus.sent]
    ok = (topics.count("route/proposed") == 3 and lp.state == L.PROPOSED and "scout/goto" in topics
          and gap not in lp.route["cells"]
          and any(d.get("outcome") == "replanning" for t, d in bus.sent if t == "log/decision"))
    print(f"schemas checked: {'yes' if bus.validate else 'no (coord.messages not on this branch)'}; "
          f"propose, fail, re-plan, verify, act, aftershock, re-plan: {'yes' if ok else 'NO'}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
