"""Stand-in lanes for tools/run_scenario.py, so the whole scenario runs before every lane is merged.

Each fake speaks only the messages in coord/CONTRACT.md, so a real lane can replace it one at a time
(`run_scenario.py --real sim,planner`). Standard library only.

The fake world is a 16 x 10 grid on layer k=0. A wall runs down column x=8 with three gaps at
y=2, y=5 and y=8. The Responder starts at (1,1); the casualty is at (14,2).
  - first route: through the gap at y=2 (predicted at risk: slab b10 leans over it)
  - the aftershock drops b10 into that gap, so the planner re-plans through y=5
  - an injected block (the unscripted change) lands on the current route; perception sees it in
    map/cells and the planner re-plans again, with no message or code written for that case
"""

import asyncio
import heapq
import random

W, H, K = 16, 10, 0
RES = 0.25  # metres per cell
WALL_X, GAPS = 8, (2, 5, 8)
START, CASUALTY = (1, 1), (14, 2)
AT_RISK = {(WALL_X, 2): "slab b10 leans over the gap"}
AFTERSHOCK_FALLS = {"b10": [(WALL_X, 2)]}


def pos(cell):
    """Centre of a cell in metres (scene frame)."""
    return [round((cell[0] + 0.5) * RES, 3), round((cell[1] + 0.5) * RES, 3), 0.0]


class FakeWorld:
    """Ground truth shared by the fake sim (physics) and fake perception (its sensors)."""

    def __init__(self, seed=7):
        self.rng = random.Random(seed)
        self.t0 = asyncio.get_event_loop().time()
        self.occupied = set()
        for x in range(W):
            self.occupied |= {(x, 0), (x, H - 1)}
        for y in range(H):
            self.occupied |= {(0, y), (W - 1, y)}
            if y not in GAPS:
                self.occupied.add((WALL_X, y))
        self.collapsed = set()
        self.blocks = [
            {"id": "b7", "label": "wall", "pos": [2.125, 1.25, 0.5], "size": [0.125, 1.25, 0.5]},
            {"id": "b10", "label": "slab", "pos": [2.125, 0.6, 0.6], "size": [0.4, 0.05, 0.3]},
        ]
        self.listeners = []  # called with the cells that changed
        self.injected = []

    def t(self):
        return round(asyncio.get_event_loop().time() - self.t0, 3)

    def blocked(self, cell):
        return cell in self.occupied or cell in self.collapsed

    async def _changed(self, cells):
        for fn in self.listeners:
            await fn(cells)

    async def aftershock(self, bus):
        moved = []
        for block, cells in AFTERSHOCK_FALLS.items():
            self.collapsed |= set(cells)
            moved.append(block)
        await bus.publish("world/change", {"kind": "aftershock", "t": self.t(), "moved_blocks": moved})
        await self._changed([c for cs in AFTERSHOCK_FALLS.values() for c in cs])

    async def inject(self, cell):
        """A block dropped by a person while the system runs. No message announces it."""
        cell = tuple(cell)
        self.occupied.add(cell)
        self.injected.append(cell)
        await self._changed([cell])


def _cell(c, occupied):
    return {"cell": [c[0], c[1], K], "state": "seen", "occupied": occupied}


async def fake_sim(bus, world):
    async def verify(route):
        bad = [c for c in route["cells"] if world.blocked((c[0], c[1]))]
        await bus.publish("route/verified", {
            "id": route["id"], "ok": not bad, "unstable_cells": bad,
            "detail": "fake physics: all cells clear" if not bad else f"{len(bad)} cell(s) blocked",
        })

    bus.subscribe("route/proposed", verify)
    await bus.publish("scene/loaded", {"scene": "backup", "blocks": world.blocks})


async def fake_perception(bus, world):
    def hazards():
        out = []
        for c, why in AT_RISK.items():
            status = "collapsed" if c in world.collapsed else "at_risk"
            why2 = "b10 fell in the aftershock" if status == "collapsed" else why
            out.append({"cell": [c[0], c[1], K], "status": status, "why": why2, "estimate": True})
        return out

    async def full_map(_=None):
        cells = [_cell((x, y), world.blocked((x, y))) for x in range(W) for y in range(H)]
        await bus.publish("map/cells", {"t": world.t(), "res": RES, "cells": cells})
        await bus.publish("map/casualties", [{
            "id": "c1", "pos": pos(CASUALTY), "confidence": round(world.rng.uniform(0.75, 0.9), 2),
            "clues": ["pose", "thermal", "sound"],
            "vitals": {"breathing_rate": world.rng.randint(12, 18), "simulated": True},
        }])
        await bus.publish("map/hazards", hazards())

    async def on_change(cells):
        await bus.publish("scout/goto", {"target": pos(cells[0]), "reason": "re-scan changed cells"})
        await bus.publish("map/cells", {
            "t": world.t(), "res": RES, "cells": [_cell(c, world.blocked(c)) for c in cells]})

    async def on_world_change(_):
        await bus.publish("map/hazards", hazards())

    bus.subscribe("scene/loaded", full_map)
    bus.subscribe("world/change", on_world_change)
    world.listeners.append(on_change)
    await bus.publish("scout/goto", {"target": pos((4, 4)), "reason": "explore toward unknown cells"})


def astar(start, goal, blocked):
    def h(c):
        return abs(c[0] - goal[0]) + abs(c[1] - goal[1])

    frontier, came, cost = [(h(start), start)], {start: None}, {start: 0}
    while frontier:
        _, cur = heapq.heappop(frontier)
        if cur == goal:
            path = []
            while cur:
                path.append(cur)
                cur = came[cur]
            return path[::-1]
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (cur[0] + dx, cur[1] + dy)
            if not (0 <= nxt[0] < W and 0 <= nxt[1] < H) or nxt in blocked:
                continue
            if cost[cur] + 1 < cost.get(nxt, 1e9):
                cost[nxt], came[nxt] = cost[cur] + 1, cur
                heapq.heappush(frontier, (cost[nxt] + h(nxt), nxt))
    return None


class FakePlanner:
    """Plan, verify, gate, move, deliver; re-plan whenever the map says the route is blocked."""

    def __init__(self, bus, world, step):
        self.bus, self.world, self.step = bus, world, step
        self.blocked, self.at_risk = set(), set()
        self.goal = None
        self.route = None  # the route being proposed, verified or driven
        self.n = 0
        self.delivery = None
        self.trigger = "casualty c1 found"
        self.done = False
        self.history = []

    async def log(self, outcome, reason, physics=""):
        await self.bus.publish("log/decision", {
            "t": self.world.t(), "perception": self.trigger, "model": "fake-astar",
            "physics": physics, "outcome": outcome, "reason": reason})

    async def plan(self, why):
        if self.goal is None or self.done:
            return
        if self.delivery:
            self.delivery.cancel()
            self.delivery = None
        self.trigger = why
        path = astar(START, self.goal, self.blocked)
        if path is None:
            await self.log("refer", "no route to the casualty")
            return
        self.n += 1
        self.route = {"id": f"r{self.n}", "robot": "responder",
                      "cells": [[x, y, K] for x, y in path], "goal": "deliver water to c1",
                      "model": "fake-astar"}
        self.history.append(self.route)
        await self.log("propose", f"{self.route['id']}: {len(path)} cells, because {why}")
        await self.bus.publish("route/proposed", self.route)

    def on_route(self, cells):
        return self.route and any((c[0], c[1]) in cells for c in self.route["cells"])

    async def on_cells(self, msg):
        newly = set()
        for c in msg["cells"]:
            xy = (c["cell"][0], c["cell"][1])
            if c["occupied"] and xy not in self.blocked:
                newly.add(xy)
            elif not c["occupied"]:
                self.blocked.discard(xy)
        self.blocked |= newly
        if newly and self.on_route(newly):
            cell = min(newly)
            await self.plan(f"map shows cell [{cell[0]},{cell[1]},0] blocked on {self.route['id']}")

    async def on_casualties(self, msg):
        if msg and self.goal is None:
            c = msg[0]
            self.goal = (int(c["pos"][0] / RES), int(c["pos"][1] / RES))
            await self.plan(f"casualty {c['id']} found (confidence {c['confidence']})")

    async def on_hazards(self, msg):
        self.at_risk = {(h["cell"][0], h["cell"][1]) for h in msg if h["status"] == "at_risk"}
        collapsed = {(h["cell"][0], h["cell"][1]) for h in msg if h["status"] == "collapsed"}
        new = collapsed - self.blocked
        self.blocked |= collapsed
        if new and self.on_route(new):
            await self.plan(f"aftershock: {msg[0]['why']}")

    async def on_world_change(self, msg):
        self.trigger = f"world/change {msg['kind']} moved {','.join(msg['moved_blocks'])}"

    async def on_verified(self, msg):
        if not self.route or msg["id"] != self.route["id"]:
            return
        if not msg["ok"]:
            await self.log("reject", msg["detail"], physics=msg["detail"])
            for c in msg["unstable_cells"]:
                self.blocked.add((c[0], c[1]))
            await self.plan(f"physics check rejected {msg['id']}")
            return
        risky = [c for c in self.route["cells"] if (c[0], c[1]) in self.at_risk]
        kind = "enter_at_risk" if risky else "risky_move"
        summary = (f"{self.route['id']} passes at-risk cell {risky[0]}" if risky
                   else f"send the Responder along {self.route['id']}")
        await self.bus.publish("gate/decision", {
            "id": f"d{self.n}", "outcome": "refer", "confidence": 0.7,
            "reason": "physics ok; a human approves the move"})
        await self.bus.publish("gate/request", {
            "id": f"g{self.n}", "kind": kind, "summary": summary, "route": self.route["id"]})

    async def on_answer(self, msg):
        if not self.route or msg["id"] != f"g{self.n}":
            return
        if not msg["approved"]:
            await self.log("hold", f"operator rejected {self.route['id']}")
            return
        await self.log("act", f"operator approved {self.route['id']}", physics="verified")
        await self.bus.publish("responder/action",
                               {"action": "move", "route": self.route["id"], "item": "water"})
        self.delivery = asyncio.ensure_future(self.deliver(self.route["id"]))

    async def deliver(self, rid):
        await asyncio.sleep(self.step)
        if self.route["id"] != rid:
            return
        self.done = True
        await self.bus.publish("responder/action", {"action": "place_supply", "route": rid,
                                                    "item": "water"})
        await self.bus.publish("say", {"to": "casualty", "intent": "reassure", "lang": "auto",
                                       "text": "Water has arrived. Help is on the way."})
        await self.log("delivered", f"water placed by c1 via {rid}")
        replans = [r["id"] for r in self.history]
        report = {"routes": replans, "re_plans": len(replans) - 1, "supplies": ["water"],
                  "casualties": [{"id": "c1", "pos": pos(self.goal), "simulated_vitals": True}],
                  "injected_blocks": [list(c) for c in self.world.injected]}
        await self.bus.publish("report/handover", {
            "json": report,
            "markdown": f"# Handover (fake)\nRoutes: {' -> '.join(replans)}. Water delivered to c1."})


async def fake_planner(bus, world, step=0.3):
    p = FakePlanner(bus, world, step)
    bus.subscribe("map/cells", p.on_cells)
    bus.subscribe("map/casualties", p.on_casualties)
    bus.subscribe("map/hazards", p.on_hazards)
    bus.subscribe("world/change", p.on_world_change)
    bus.subscribe("route/verified", p.on_verified)
    bus.subscribe("gate/answer", p.on_answer)
    return p


async def fake_voice(bus, world):
    bus.subscribe("say", lambda m: print(f"  [voice stand-in] to {m['to']}: {m['text']}"))
