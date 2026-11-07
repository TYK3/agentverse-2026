"""X3: Scout -> Responder handoff and re-splitting the work when one robot is blocked.

Three jobs, all local (no Gemini call):

1. Handoff. Every casualty perception reports (`map/casualties`) is queued for the Responder, the
   most confident first. When the Responder is free the handoff starts a T13 mission
   (`loop.mission`) to the nearest seen, free floor cell beside the casualty, with the next supply
   (water, then first_aid_kit, then radio). If no such cell is mapped yet, the Scout is sent to
   look (`scout/goto`).
2. Human gate only on low confidence. The handoff adds no gate of its own: the T13 loop already
   acts at confidence >= 0.8, re-looks from 0.5 and refers to a human below that (its confidence is
   min(casualty confidence, share of route cells seen)). So a confident casualty goes straight to
   `responder/action`, and only a doubtful one reaches `gate/request`.
3. Re-split when one robot is blocked.
   - Responder blocked (sim `log/decision` outcome "blocked"): the Scout takes over the spot,
     re-looking where the Responder stopped; the casualty goes back in the queue and is tried again
     once the map has been re-scanned (MAX_ATTEMPTS in all).
   - Scout blocked (`sensors/scout` motion.state "blocked"): perception's Explorer already drops the
     blocked target and picks the Scout's next frontier, so the handoff does not send a competing
     scout/goto; its part is to log the block and keep the Responder working its casualty queue.

Inputs: map/cells (via the router), map/hazards, map/casualties, sensors/scout, log/decision (the
sim Responder's outcomes, model "sim"), world/change. Outputs: loop.mission calls, scout/goto and
log/decision (model "local-handoff").
"""

from __future__ import annotations

import math
import re
from collections import deque

from planner.route import _cell, _neighbours, _read_map

SUPPLIES = ("water", "first_aid_kit", "radio")
MAX_ATTEMPTS = 2          # Responder tries per casualty before the handoff gives up on it
GOAL_RADIUS_M = 0.5       # the Responder stops on a free cell within this distance of the casualty
SCOUT_NOTE_EVERY_S = 5.0  # log a Scout block at most this often (its blocked state repeats every frame)
LOOK_EVERY_S = 10.0       # ask the Scout to look beside a casualty at most this often (it is mid-route)
START_SNAP_M = 0.35       # search from the nearest free cell this close if the Responder's own cell looks occupied
RESPONDER_START = (-10, -42, 0)   # sim/scenes/backup.xml: the Responder starts at x -0.5, y -2.1
MODEL = "local-handoff"
_AT = re.compile(r"responder at \[(-?[\d.]+), (-?[\d.]+)\]")


class Handoff:
    def __init__(self, bus, loop, router, *, responder_start=RESPONDER_START, clock=None):
        self.bus, self.loop, self.router = bus, loop, router
        self.clock = clock or (lambda: loop._t())
        self.responder_cell = tuple(responder_start)
        self.scout_cell = None
        self.casualties = {}       # id -> latest map/casualties entry
        self.attempts = {}         # casualty id -> missions started for it
        self.served = set()        # casualty ids that got a supply
        self.skipped = set()       # casualty ids given up on
        self.active = None         # casualty id of the running mission
        self.hazards = []
        self.waiting_scan = False  # after a block: wait for the next map/cells before retrying
        self.scout_blocked_at = None
        self.last_scout_note = float("-inf")
        self.last_look = {}        # casualty id -> clock() of the last look request
        self.decisions = []        # every log/decision this module published

    def attach(self):
        for topic, fn in (("map/casualties", self.on_casualties), ("map/cells", self.on_map),
                          ("map/hazards", self.on_hazards), ("sensors/scout", self.on_sensors),
                          ("log/decision", self.on_log), ("world/change", self.on_world_change)):
            self.bus.subscribe(topic, fn)
        return self

    # ---- helpers ----------------------------------------------------------------------------

    async def log(self, perception, outcome, reason):
        data = {"t": self.clock(), "perception": perception, "model": MODEL, "physics": "",
                "outcome": outcome, "reason": reason}
        self.decisions.append(data)
        await self.bus.publish("log/decision", data)

    def _map(self):
        cells = self.router.map_cells
        return _read_map(cells) if cells and cells.get("cells") else (None, {})

    def _safe(self, records):
        blocked = {_cell(h["cell"]) for h in self.hazards if h["status"] != "stable"}
        return {c for c, r in records.items()
                if c[2] == 0 and r["state"] == "seen" and not r["occupied"] and c not in blocked}, blocked

    def _reachable(self, start, safe):
        if start not in safe:
            return set()
        seen, queue = {start}, deque([start])
        while queue:
            for other, _ in _neighbours(queue.popleft(), safe):
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
        return seen

    def goal_for(self, casualty):
        """Nearest seen, free, reachable floor cell within GOAL_RADIUS_M of the casualty, or None."""
        res, records = self._map()
        if not records:
            return None
        safe, _ = self._safe(records)
        start = self.start_cell(safe, res)
        if start is None:
            return None
        reachable = self._reachable(start, safe)
        x, y = casualty["pos"][:2]
        best = None
        for c in reachable:
            d = math.hypot((c[0] + 0.5) * res - x, (c[1] + 0.5) * res - y)
            if d <= GOAL_RADIUS_M and (best is None or (d, c) < best):
                best = (d, c)
        return best[1] if best else None

    def start_cell(self, safe=None, res=0.05):
        """The Responder's cell, or the nearest seen free cell within START_SNAP_M of it (its own body,
        or rubble beside it, can make its exact cell look occupied on the map); None if none."""
        if safe is None:
            res, records = self._map()
            safe, _ = self._safe(records) if records else (set(), set())
        if self.responder_cell in safe:
            return self.responder_cell
        rx, ry, _ = self.responder_cell
        near = [(math.hypot(c[0] - rx, c[1] - ry) * res, c) for c in safe
                if abs(c[0] - rx) * res <= START_SNAP_M and abs(c[1] - ry) * res <= START_SNAP_M]
        near = [(d, c) for d, c in near if d <= START_SNAP_M]
        return min(near)[1] if near else None

    def _queue(self):
        return sorted((c for cid, c in self.casualties.items() if cid not in self.served | self.skipped),
                      key=lambda c: (-c["confidence"], c["id"]))

    def _cell_of(self, x, y, res=0.05):
        # The epsilon keeps a position printed to 2 decimals on its own cell (1.4 / 0.05 = 27.999...).
        return (math.floor(x / res + 1e-6), math.floor(y / res + 1e-6), 0)

    # ---- the handoff --------------------------------------------------------------------------

    async def dispatch(self):
        """Start a Responder mission for the best waiting casualty, if the Responder is free."""
        if self.active or self.waiting_scan:
            return None
        for cas in self._queue():
            cid = cas["id"]
            goal = self.goal_for(cas)
            if goal is None:
                if self.clock() - self.last_look.get(cid, float("-inf")) >= LOOK_EVERY_S:
                    self.last_look[cid] = self.clock()
                    x, y, z = cas["pos"]
                    await self.bus.publish("scout/goto", {"target": [x, y, z],
                                                          "reason": f"handoff: map a free cell beside casualty {cid}"})
                    await self.log(f"casualty {cid} confidence {cas['confidence']:.2f}", "relook",
                                   f"no free reachable cell within {GOAL_RADIUS_M} m of {cid} yet; Scout sent to look")
                continue
            item = SUPPLIES[len(self.served) % len(SUPPLIES)]
            self.attempts[cid] = self.attempts.get(cid, 0) + 1
            self.active = cid
            await self.log(f"casualty {cid} confidence {cas['confidence']:.2f}, clues {', '.join(cas.get('clues', []))}",
                           "handoff", f"Scout hands {cid} to the Responder: {item} to cell {list(goal)} "
                                      f"(try {self.attempts[cid]}/{MAX_ATTEMPTS}); T13 gates by confidence")
            await self.loop.mission(list(self.start_cell()), list(goal), goal_text=f"deliver {item} to {cid}",
                                    item=item, casualty=cid)
            return cid
        return None

    async def on_casualties(self, data):
        for c in data:
            self.casualties[c["id"]] = c
        await self.dispatch()

    async def on_map(self, data):
        if self.waiting_scan:
            self.waiting_scan = False
        await self.dispatch()

    def on_hazards(self, data):
        self.hazards = list(data)

    # ---- outcomes from the sim Responder and the T13 loop -------------------------------------

    async def on_log(self, data):
        if data.get("model") == MODEL:
            return
        reason, outcome = data.get("reason", ""), data.get("outcome", "")
        if data.get("model") == "sim":
            at = _AT.search(data.get("perception", ""))
            if at:
                self.responder_cell = self._cell_of(float(at.group(1)), float(at.group(2)))
            if outcome == "done" and reason.startswith("placed") and self.active:
                self.served.add(self.active)
                await self.log(f"Responder at {list(self.responder_cell)}", "done",
                               f"{reason} for {self.active}; next casualty")
                self.active = None
                await self.dispatch()
            elif outcome in ("blocked", "frozen") and self.active:
                await self.responder_blocked(outcome, reason)
        elif outcome == "hold" and self.active and self.loop.state == "IDLE":
            # T13 refused or a human declined: the casualty stays queued but this mission is over.
            await self.give_up_or_retry(f"T13 hold: {reason}")

    async def responder_blocked(self, outcome, reason):
        x, y = ((self.responder_cell[0] + 0.5) * 0.05, (self.responder_cell[1] + 0.5) * 0.05)
        if outcome == "blocked":
            await self.bus.publish("scout/goto", {"target": [round(x, 3), round(y, 3), 0.075],
                                                  "reason": f"re-split: Responder blocked near [{x:.2f}, {y:.2f}], "
                                                            f"Scout re-scans it"})
        await self.give_up_or_retry(f"Responder {outcome}: {reason}")

    async def give_up_or_retry(self, why):
        cid, self.active = self.active, None
        if self.attempts.get(cid, 0) >= MAX_ATTEMPTS:
            self.skipped.add(cid)
            await self.log(f"casualty {cid}", "skipped", f"{why}; {MAX_ATTEMPTS} tries used, next casualty")
            return await self.dispatch()
        self.waiting_scan = True
        await self.log(f"casualty {cid}", "requeued", f"{why}; retry after the Scout re-scans")

    async def on_world_change(self, data):
        if self.active:
            # T13 drops the route and re-plans on the next scan; keep the casualty as the active job.
            await self.log(f"{data.get('kind')} during handoff of {self.active}", "waiting",
                           "T13 re-plans after the re-scan; handoff keeps the casualty assigned")

    # ---- Scout blocked: the Responder keeps working -------------------------------------------------

    async def on_sensors(self, data):
        pos = data.get("pose", {}).get("pos")
        if pos:
            self.scout_cell = self._cell_of(pos[0], pos[1])
        motion = data.get("motion") or {}
        target = motion.get("target")
        if motion.get("state") != "blocked" or not target:
            self.scout_blocked_at = None if motion.get("state") == "moving" else self.scout_blocked_at
            return
        if self.scout_blocked_at == tuple(target) or self.clock() - self.last_scout_note < SCOUT_NOTE_EVERY_S:
            return                                   # already noted this block (or one moments ago)
        self.scout_blocked_at, self.last_scout_note = tuple(target), self.clock()
        await self.resplit_scout(target)

    async def resplit_scout(self, blocked_target):
        """The Scout's own frontier choice stays with perception's Explorer, which drops a blocked
        target and picks the next frontier itself; a second scout/goto from here would fight it (seen
        in a real-lane run: the two alternated every tick and the Scout never explored). The handoff's
        share of the re-split is the Responder: it keeps working its casualty queue meanwhile."""
        where = f"[{blocked_target[0]:.2f}, {blocked_target[1]:.2f}]"
        await self.log(f"Scout blocked going to {where}", "resplit",
                       "Explorer re-picks the Scout's frontier; Responder continues its casualty queue")
        await self.dispatch()


def start(bus, loop, router, **kw):
    """Attach the handoff to the hub bus beside the T13 loop; returns it."""
    return Handoff(bus, loop, router, **kw).attach()
