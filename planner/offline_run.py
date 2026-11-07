"""Scripted T15 run: the link drops, the operator speaks, and a full cycle completes on this device.

    ollama serve & ollama pull gemma4:e2b     # optional: without it the goal is read by keywords
    python -m planner.offline_run

Link off -> operator/command read by the local model -> local A* route -> physics verdict (scripted
here) -> rule-based gate -> act. Then the link returns and the offline route is re-checked online
(skipped with GEMINI_MODE=off). Prints status/budget and whether it is within planner/budget.json.
"""

import asyncio
import sys
import time

from planner import budget as B
from planner import local_llm
from planner import loop as L
from planner.loop_run import PrintBus, room
from planner.route import RoutePlanner

PLACES = {"back room": [8, 3, 0], "left room": [8, 6, 0], "corridor": [2, 0, 0]}


async def run():
    warm = await asyncio.to_thread(local_llm.warm)
    print(f"local model {local_llm.MODEL_TAG}: {'loaded' if warm else 'unavailable, keyword stand-in'}",
          file=sys.stderr)
    bus = PrintBus()
    router = RoutePlanner(bus)
    bus.subscribe("map/cells", router.update_map)
    budget = B.Budget(bus)
    lp = L.Loop(bus, router, budget=budget, places=PLACES, start_cell=(0, 3, 0),
                interpret=local_llm.interpret).attach()
    await bus.publish("map/cells", room())
    await bus.publish("map/hazards", [])
    await bus.publish("status/link", {"online": False})
    t = time.perf_counter()
    await bus.publish("operator/command", {"text": "send the radio to the left room, no, the back room",
                                           "source": "voice"})
    read_ms = (time.perf_counter() - t) * 1000
    await bus.publish("route/verified", {"id": lp.route["id"], "ok": True, "unstable_cells": [], "detail": ""})
    msg = budget.message()
    await bus.publish("status/budget", msg)
    await bus.publish("status/link", {"online": True})
    goal = next(d for t_, d in bus.sent if t_ == "log/decision" and d["outcome"] == "goal")
    ok = lp.state == L.EXECUTING and lp.route["cells"][-1] == PLACES["back room"]
    print(f"goal read by {goal['model']} in {read_ms:.0f} ms; cycle completed offline: {'yes' if ok else 'NO'}; "
          f"budget {msg['mem_mb']:.0f} MB / {msg['limit']['mem_mb']} MB, {msg['ms_per_step']:.0f} ms / "
          f"{msg['limit']['ms_per_step']} ms per step: {'within' if budget.within(msg) else 'OVER'}",
          file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
