"""X3: Scout -> Responder handoff and re-splitting the work when one robot is blocked.

Three jobs, all local (no Gemini call):

1. Handoff. Every casualty perception reports (`map/casualties`) is queued for the Responder, the
   most confident first. When the Responder is free the handoff starts a T13 mission
   (`loop.mission`) to the nearest seen, free floor cell beside the casualty. Y2: the supply is
   chosen from the casualty's injuries (planner/supply.py: `injuries` on map/casualties or Y3's
   `casualty/triage`), from the kit still on the deck or, for a fracture once the kit splint is gone,
   a board the Scout's depth points found: then the Responder first fetches the board (move + grip)
   and then carries it to the casualty. With no injury known it brings the next supply in turn
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

from planner import supply
from planner.route import _cell, _neighbours, _read_map

SUPPLIES = ("water", "first_aid_kit", "radio")
MAX_ATTEMPTS = 2          # Responder tries per casualty before the handoff gives up on it
GOAL_RADIUS_M = 0.5       # the Responder stops on a free cell within this distance of the casualty
BOARD_RADIUS_M = 0.35     # ... and within this of a board it fetches (sim gripper reach is 0.45 m)
SCOUT_NOTE_EVERY_S = 5.0  # log a Scout block at most this often (its blocked state repeats every frame)
RETRY_AFTER_S = 5.0       # after a block, retry no sooner than this (time for the Scout to re-scan)
LOOK_EVERY_S = 10.0       # ask the Scout to look beside a casualty at most this often (it is mid-route)
START_SNAP_M = 0.35       # search from the nearest free cell this close if the Responder's own cell looks occupied
RESPONDER_START = (-10, -36, 0)   # sim/scenes/backup.xml: the Responder starts at x -0.5, y -1.77
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
        self.blocked_at = float("-inf")
        self.last_look = {}        # casualty id -> clock() of the last look request
        self.decisions = []        # every log/decision this module published
        self.kit = set(supply.KIT)  # supplies still on the Responder's deck (Y2)
        self.triage = {}           # casualty id -> injuries from casualty/triage (Y3)
        self.finder = supply.BoardFinder()
        self.fetching = None       # {"cid", "block", "item"} while the Responder fetches found material
        self.holding_block = None  # a found block gripped and not yet placed

    def attach(self):
        for topic, fn in (("map/casualties", self.on_casualties), ("map/cells", self.on_map),
                          ("map/hazards", self.on_hazards), ("sensors/scout", self.on_sensors),
                          ("log/decision", self.on_log), ("world/change", self.on_world_change),
                          ("scene/loaded", self.finder.on_scene), ("casualty/triage", self.on_triage)):
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

    def goal_for(self, casualty, radius=GOAL_RADIUS_M):
        """Nearest seen, free, reachable floor cell within `radius` of the casualty (or any {"pos"}), or None."""
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
            if d <= radius and (best is None or (d, c) < best):
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
            item, block, why = self.pick(cas)
            if block and block != self.holding_block:
                board = next((b for b in self.finder.boards() if b["block"] == block), None)
                near = self.goal_for({"pos": board["pos"]}, BOARD_RADIUS_M) if board else None
                if near is None:
                    item, block, why = "first_aid_kit", None, f"{why}; board not reachable on the map yet, first aid kit"
                else:
                    self.attempts[cid] = self.attempts.get(cid, 0) + 1
                    self.active, self.fetching = cid, {"cid": cid, "block": block, "item": item}
                    await self.log(f"casualty {cid} confidence {cas['confidence']:.2f}", "handoff",
                                   f"Responder fetches {block} for {cid} first ({why}), from cell {list(near)}")
                    await self.loop.mission(list(self.start_cell()), list(near), goal_text=f"fetch {block} as a {item} for {cid}",
                                            item=item, casualty=cid, action="fetch", block=block)
                    return cid
            self.attempts[cid] = self.attempts.get(cid, 0) + 1
            self.active = cid
            what = f"{block} as a {item}" if block else item
            await self.log(f"casualty {cid} confidence {cas['confidence']:.2f}, clues {', '.join(cas.get('clues', []))}",
                           "handoff", f"Scout hands {cid} to the Responder: {what} to cell {list(goal)} "
                                      f"(try {self.attempts[cid]}/{MAX_ATTEMPTS}); {why}; T13 gates by confidence")
            await self.loop.mission(list(self.start_cell()), list(goal), goal_text=f"deliver {what} to {cid}",
                                    item=item, casualty=cid, block=block)
            return cid
        return None

    def injuries_of(self, cas):
        return list(cas.get("injuries") or []) + list(self.triage.get(cas["id"], []))

    def pick(self, cas):
        """(item, block or None, why) for this casualty: planner/supply.py from its injuries, else the
        next supply in turn that is still on the deck."""
        if self.holding_block and self.fetching and self.fetching["cid"] == cas["id"]:
            return self.fetching["item"], self.holding_block, "carrying the found material already"
        got = supply.choose(self.injuries_of(cas), self.kit, self.finder.best(near=cas["pos"][:2]))
        if got:
            return got["item"], got["block"], got["why"]
        turn = [s for s in SUPPLIES if s in self.kit] or [s for s in supply.KIT if s in self.kit] or ["water"]
        return turn[0], None, "no injury known: next supply in turn"   # used supplies leave self.kit

    def on_triage(self, data):
        """Y3 casualty/triage: {id, injuries, ...} (one entry or a list); keeps each casualty's injuries."""
        for entry in data if isinstance(data, list) else [data]:
            if entry.get("id"):
                self.triage[entry["id"]] = list(entry.get("injuries") or []) + (
                    [entry["recommended_action"]] if entry.get("recommended_action") else [])

    async def on_casualties(self, data):
        for c in data:
            self.casualties[c["id"]] = c
        await self.dispatch()

    async def on_map(self, data):
        # Retry only once the Scout has had time to re-scan (a map update every 0.5 s is not a re-scan).
        if self.waiting_scan and self.clock() - self.blocked_at >= RETRY_AFTER_S:
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
            if outcome == "done" and self.fetching and reason.startswith(f"gripped {self.fetching['block']}"):
                return await self.deliver_found(reason)
            if outcome == "done" and reason.startswith("placed") and self.active:
                placed = reason.split()[1]
                self.kit.discard(placed)
                if placed == self.holding_block:
                    self.finder.taken.add(placed)
                    self.holding_block, self.fetching = None, None
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

    async def deliver_found(self, reason):
        """Leg 2 of found material: the board is in the gripper; carry it to the casualty."""
        cid, block, item = self.fetching["cid"], self.fetching["block"], self.fetching["item"]
        self.holding_block = block
        cas = self.casualties.get(cid)
        goal = self.goal_for(cas) if cas else None
        if goal is None:
            return await self.give_up_or_retry(f"{reason}; no free cell beside {cid} for the {item}")
        await self.log(f"Responder at {list(self.responder_cell)}", "handoff",
                       f"{reason}; carrying {block} as a {item} to {cid} at cell {list(goal)}")
        await self.loop.mission(list(self.start_cell()), list(goal), goal_text=f"deliver {block} as a {item} to {cid}",
                                item=item, casualty=cid, block=block)

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
        self.waiting_scan, self.blocked_at = True, self.clock()
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
        self.finder.on_sensors(data)
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
