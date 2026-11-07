"""T13: propose, physics-verify, gate, act, and re-plan visibly on world/change.

States: IDLE -> PROPOSED -> VERIFIED -> GATED -> EXECUTING. Everything runs locally. The only
Gemini call is the optional online review of a verified route, through coord/gem.py, with a 5 s
timeout; it never blocks the decision (off, error or timeout: "online_review" says so in the log).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time

from planner.route import RoutePlanner

IDLE, PROPOSED, VERIFIED, GATED, EXECUTING = "IDLE", "PROPOSED", "VERIFIED", "GATED", "EXECUTING"
ACT, RELOOK = 0.8, 0.5  # confidence >= ACT acts, >= RELOOK re-looks, below refers to a human
MAX_REPLANS = 3  # physics rejections in a row before the gate refers to a human
REVIEW_TIMEOUT_S = 5.0
GATE_TIMEOUT_S = 60.0
REPLAN_EVERY_S = 1.0  # while waiting for a re-scan, try a new route at most once a second
MODEL = "local-astar"


def gate_outcome(confidence: float) -> str:
    if confidence >= ACT:
        return "act"
    return "relook" if confidence >= RELOOK else "refer"


def _gem():
    try:
        from coord import gem
        return gem
    except ImportError:
        return None


class Loop:
    """One Responder mission at a time. Start it with `await loop.mission(start, goal, ...)`."""

    def __init__(self, bus, router: RoutePlanner, *, gem=None, clock=time.monotonic,
                 review_timeout=REVIEW_TIMEOUT_S, budget=None, places=None, start_cell=None, interpret=None,
                 gate_timeout=GATE_TIMEOUT_S):
        if not 0 < gate_timeout <= GATE_TIMEOUT_S:
            raise ValueError("gate timeout must be positive and at most 60 seconds")
        self.bus, self.router = bus, router
        self.budget = budget  # planner.budget.Budget: times each local step for status/budget
        self.places = places or {}  # operator place name -> goal cell, for operator/command
        self.start_cell = start_cell  # () -> the Responder's current cell
        self.interpret = interpret  # (text, place names) -> {place, item, why, model}; planner.local_llm
        self.online = True  # from status/link
        self.offline_acts: list[dict] = []  # routes acted on while offline, re-checked when the link returns
        self.gem = gem if gem is not None else _gem()
        self.clock, self.t0 = clock, clock()
        self.review_timeout = review_timeout
        self.state = IDLE
        self.mission_args: dict | None = None
        self.route: dict | None = None  # the current route/proposed payload
        self.hazards: list[dict] = []  # from perception
        self.unstable: dict[tuple, str] = {}  # cell -> why, from physics rejections
        self.casualties: dict[str, dict] = {}
        self.replans = 0
        self.waiting_scan: str | None = None  # why we are waiting for the map to change
        self.map_version = 0
        self.scan_from_version = 0
        self.last_try = float("-inf")
        self.request: dict | None = None  # open gate/request
        self.gate_timeout = gate_timeout
        self._gate_timer = None
        self._gate_deadline = None
        self._gate_tasks = set()
        self.verified_route: str | None = None
        self.review = "not run"
        self._n = {"d": 0, "g": 0}

    # ---- wiring -------------------------------------------------------------------------------

    def attach(self):
        for topic, fn in (("route/verified", self.on_verified), ("world/change", self.on_world_change),
                          ("map/cells", self.on_map), ("map/hazards", self.on_hazards),
                          ("map/casualties", self.on_casualties), ("gate/answer", self.on_answer),
                          ("status/link", self.on_link), ("operator/command", self.on_command)):
            self.bus.subscribe(topic, fn)
        return self

    def _id(self, kind):
        self._n[kind] += 1
        return f"{kind}{self._n[kind]}"

    def _step(self):
        return self.budget.step() if self.budget else contextlib.nullcontext()

    def _t(self):
        return round(max(0.0, self.clock() - self.t0), 2)

    async def log(self, perception, outcome, reason, physics="", model=MODEL):
        await self.bus.publish("log/decision", {"t": self._t(), "perception": perception, "model": model,
                                                "physics": physics, "outcome": outcome, "reason": reason})

    async def decide(self, outcome, confidence, reason):
        await self.bus.publish("gate/decision", {"id": self._id("d"), "outcome": outcome,
                                                 "confidence": round(confidence, 3), "reason": reason})

    # ---- mission and proposals ----------------------------------------------------------------

    async def mission(self, start, goal, *, goal_text="deliver water to c1", item="water", casualty="c1",
                      action="deliver"):
        if item not in ("water", "first_aid_kit", "radio") or action not in ("deliver", "grip"):
            raise ValueError("unsupported Responder item or action")
        await self.cancel_request("mission replaced")
        self.mission_args = {"start": tuple(start), "goal": tuple(goal), "goal_text": goal_text,
                             "item": item, "casualty": casualty, "action": action}
        self.replans, self.unstable = 0, {}
        return await self.propose(f"mission: {goal_text}")

    async def propose(self, why):
        await self.cancel_request("route replaced")
        self.verified_route = None
        m = self.mission_args
        self.router.hazards = self.hazards + [
            {"cell": list(c), "status": "at_risk", "why": w, "estimate": True} for c, w in self.unstable.items()]
        with self._step():
            result = await self.router.propose(m["start"], m["goal"], goal_text=m["goal_text"], publish=False)
        if result["status"] == "ok":
            self.route, self.state, self.waiting_scan = result["proposal"], PROPOSED, None
            await self.log(why, "proposed", f"route {self.route['id']}: {len(self.route['cells'])} seen cells "
                           f"to {m['goal_text']}, waiting for the physics check")
            # A sim subscriber may answer inside publish(), so register the route first.
            await self.bus.publish("route/proposed", result["proposal"])
            return result
        # No route over seen cells: re-look at the frontier and try again when the map changes.
        self.route, self.state = None, IDLE
        targets = result.get("cells") or [list(m["goal"])]
        await self.decide("relook", 0.0, f"no route over seen cells ({why}); scanning cell {targets[0]}")
        await self.goto(targets[0], f"re-look at cell {targets[0]}: no verified route yet")
        await self.wait_for_scan(self.waiting_scan or "no route over seen cells")  # keep the first trigger
        return result

    async def goto(self, cell, reason):
        res = (self.router.map_cells or {}).get("res", 0.05)
        target = [round((n + 0.5) * res, 3) for n in cell]  # cell centre; cell = floor(pos / res)
        await self.bus.publish("scout/goto", {"target": target, "reason": reason})

    async def wait_for_scan(self, why):
        self.waiting_scan, self.scan_from_version = why, self.map_version

    # ---- physics result, gate and online review -----------------------------------------------

    async def on_verified(self, data):
        if not self.route or data["id"] != self.route["id"] or self.state != PROPOSED:
            return
        rid = data["id"]
        if not data["ok"]:
            for c in data["unstable_cells"]:
                self.unstable[tuple(c)] = f"physics check on {rid}: {data['detail'] or 'unstable'}"
            self.replans += 1
            physics = f"{rid} rejected: {data['detail'] or 'unstable'}; unstable {data['unstable_cells']}"
            if self.replans > MAX_REPLANS:
                return await self.refer(0.0, f"physics rejected {self.replans} routes in a row", physics)
            await self.log("physics check", "replanning", f"avoiding {len(data['unstable_cells'])} unstable "
                           f"cells, re-plan {self.replans} of {MAX_REPLANS}", physics=physics)
            return await self.propose(f"re-plan after {rid} failed the physics check")
        self.state, self.replans = VERIFIED, 0
        self.verified_route = rid
        await self.gate(f"{rid} verified: {data['detail'] or 'stable'}")

    def confidence(self):
        """min(casualty confidence, fraction of route cells that are seen), plus the weakest cell."""
        records = {tuple(r["cell"]): r for r in (self.router.map_cells or {}).get("cells", [])}
        cells = self.route["cells"]
        unseen = [c for c in cells if records.get(tuple(c), {}).get("state") != "seen"]
        seen_frac = 1 - len(unseen) / len(cells)
        cid = self.mission_args["casualty"]
        cas = self.casualties.get(cid) if cid else None
        cas_conf = cas["confidence"] if cas else (RELOOK if cid else 1.0)  # unconfirmed casualty: re-look
        why = f"{len(cells) - len(unseen)}/{len(cells)} route cells seen"
        if cid:
            why += f", casualty {cid} " + (f"confidence {cas_conf:.2f}" if cas else "not yet detected")
        # The weakest link: an unseen route cell if the route is the doubt, else the casualty at the goal.
        weakest = unseen[0] if unseen and seen_frac <= cas_conf else list(self.mission_args["goal"])
        return min(cas_conf, seen_frac), why, weakest

    async def gate(self, physics):
        self.state = GATED
        with self._step():
            conf, why, weakest = self.confidence()
            outcome = gate_outcome(conf)
        rid = self.route["id"]
        if outcome == "act":
            agree, review_why = await self.online_review()
            if not self.route or self.route["id"] != rid or self.state != GATED:
                return  # a scene change or replacement mission invalidated the review
            if agree is False:
                return await self.refer(conf, f"online review disagrees: {review_why}", physics)
            if not self.online:
                self.offline_acts.append({"route": self.route, "hazards": list(self.router.hazards)})
            await self.decide("act", conf, f"{rid} verified and {why}; online review {self.review}")
            await self.log(why, "act", f"send the Responder along {rid}", physics=physics, model=self._model())
            return await self.execute(expected_route=rid)
        if outcome == "relook":
            cell = weakest
            await self.decide("relook", conf, f"{why}; re-look at cell {cell} before acting")
            await self.log(why, "relook", f"Scout re-scans cell {cell}", physics=physics)
            await self.goto(cell, f"re-look at cell {cell}: {why}")
            self.state = IDLE
            return await self.wait_for_scan(f"re-look at cell {cell}")
        await self.refer(conf, why, physics)

    async def online_review(self, route=None, hazards=None):
        """Ask gemini-4-argon to double-check a verified route; (None, why) when it could not run."""
        gem = self.gem
        if not self.online:
            self.review = "skipped (offline, re-checked when the link returns)"
            return None, self.review
        if gem is None or getattr(gem, "MODE", "off") == "off":
            self.review = "stand-in (gemini off)"
            if gem is not None:
                gem.mark_stand_in("route_review")
            return None, self.review
        prompt = ("You double-check a rescue robot route. The route was already verified by a physics "
                  "check. Reply with JSON only: {\"agree\": true|false, \"why\": \"one line\"}.\n"
                  + json.dumps({"route": route or self.route,
                                "hazards": self.router.hazards if hazards is None else hazards,
                                "map": self.map_summary()}))
        try:
            text = await asyncio.wait_for(asyncio.to_thread(
                gem.ask, "lead_reasoning", prompt, thinking="low", feature="route_review"), self.review_timeout)
            match = re.search(r"\{.*\}", text, re.DOTALL)
            verdict = json.loads(match.group(0)) if match else {}
            if not isinstance(verdict.get("agree"), bool):
                raise TypeError(f"unusable reply: {text[:80]!r}")
        except Exception as e:  # noqa: BLE001 -- GeminiOff, timeout, network, cap or a bad reply: continue locally
            self.review = "skipped"
            return None, f"skipped ({type(e).__name__})"
        self.review = "agrees" if verdict["agree"] else "disagrees"
        return verdict["agree"], str(verdict.get("why", ""))[:200]

    def _model(self):
        return MODEL + (" + gemini-4-argon review" if self.review in ("agrees", "disagrees") else "")

    def map_summary(self):
        counts: dict[str, int] = {}
        for r in (self.router.map_cells or {}).get("cells", []):
            key = r["state"] + (" occupied" if r["occupied"] else "")
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _clear_request(self):
        request, self.request = self.request, None
        if self._gate_timer is not None:
            self._gate_timer.cancel()
            self._gate_timer = None
        self._gate_deadline = None
        return request

    async def cancel_request(self, why):
        request = self._clear_request()
        if request:
            await self.log(f"gate {request['id']}", "hold", f"approval cancelled: {why}")

    def _arm_timeout(self):
        request_id = self.request["id"]
        self._gate_deadline = self.clock() + self.gate_timeout

        def expire():
            task = asyncio.create_task(self._expire_request(request_id))
            self._gate_tasks.add(task)
            task.add_done_callback(self._gate_tasks.discard)

        self._gate_timer = asyncio.get_running_loop().call_later(self.gate_timeout, expire)

    async def _expire_request(self, request_id):
        if self.request and self.request["id"] == request_id:
            self._clear_request()
            self.state = IDLE
            await self.log(f"gate {request_id}", "hold", "approval timeout: refused; Responder idle")

    async def refer(self, conf, why, physics="", *, kind="risky_move"):
        await self.cancel_request("new approval request")
        self.state = GATED
        rid = self.route["id"] if self.route else "none"
        self.request = {"id": self._id("g"), "kind": kind, "route": rid,
                        "summary": f"{self.mission_args['goal_text']} via {rid}: {why}"}
        self._arm_timeout()
        await self.decide("refer", conf, why)
        await self.log(why, "refer", f"a human decides on {rid}", physics=physics)
        if self.request:
            await self.bus.publish("gate/request", dict(self.request))

    async def prepare_emergency_call(self, summary):
        """Show a prepared message and request approval; never contact any phone service."""
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("emergency summary is required")
        await self.cancel_request("emergency message prepared")
        self.state = GATED
        self.request = {"id": self._id("g"), "kind": "emergency_call",
                        "route": self.route["id"] if self.route else "none",
                        "summary": f"Prepared emergency message: {summary}"}
        request = dict(self.request)
        self._arm_timeout()
        await self.log(summary, "refer", "emergency message prepared for operator approval; no call placed")
        await self.bus.publish("gate/request", request)
        return request

    async def on_answer(self, data):
        if not self.request or data.get("id") != self.request["id"]:
            return
        if data.get("by", "operator") != "operator":
            return
        if self.clock() >= self._gate_deadline:
            return await self._expire_request(self.request["id"])
        req = self._clear_request()  # consume once, before any await/re-entrant publish
        if data.get("approved") is True and req["kind"] == "emergency_call":
            self.state = IDLE
            return await self.log(f"operator approved {req['id']}", "prepared",
                                  f"{req['summary']}; operator must place the call; no call placed")
        if data.get("approved") is True and self.route and req["route"] == self.route["id"]:
            await self.log(f"operator approved {req['id']}", "act", f"human approved {self.route['id']}")
            return await self.execute(approved_kind=req["kind"], expected_route=req["route"])
        self.state = IDLE
        await self.log(f"operator rejected {req['id']}", "hold", "approval refused; Responder idle")

    def execution_risk(self):
        """Recheck observations and physics; human approval never overrides a collapsed cell."""
        if not self.route or self.route["id"] != self.verified_route:
            return "hold", "route has no successful physics verification"
        records = {tuple(r["cell"]): r for r in (self.router.map_cells or {}).get("cells", [])}
        cells = {tuple(c) for c in self.route["cells"]}
        if any(records.get(c, {}).get("state") != "seen" or records[c]["occupied"] for c in cells):
            return "hold", "route is no longer fully seen and free"
        if any(c in self.unstable for c in cells):
            return "hold", "route includes physics-rejected cells"
        if any(tuple(h["cell"]) in cells and h["status"] == "collapsed" for h in self.hazards):
            return "hold", "route includes a collapsed cell"
        if any(tuple(h["cell"]) in cells and h["status"] == "at_risk" for h in self.hazards):
            return "enter_at_risk", "route enters an at-risk cell; includes any requested supply grip"
        if self.mission_args["action"] == "grip":
            return "risky_move", "grip the requested supply, then place it; obstacle targeting is not on this wire interface"
        return None, "seen, free and physics verified"

    async def execute(self, *, approved_kind=None, expected_route=None):
        if expected_route is not None and (not self.route or self.route["id"] != expected_route):
            return await self.log("execution check", "hold", "stale dispatch discarded; route changed")
        kind, why = self.execution_risk()
        if kind == "hold":
            self.state = IDLE
            return await self.log("execution check", "hold", f"{why}; Responder idle")
        if kind and approved_kind != kind:
            return await self.refer(self.confidence()[0], why, kind=kind)
        rid, item = self.route["id"], self.mission_args["item"]
        self.state = EXECUTING
        actions = ["move"] + (["grip"] if self.mission_args["action"] == "grip" else [])
        for action in actions + ["place_supply", "release"]:
            if not self.route or self.route["id"] != rid or self.state != EXECUTING:
                return
            current_kind, why = self.execution_risk()
            if current_kind == "hold" or (current_kind and current_kind != approved_kind):
                self.state = IDLE
                return await self.log("execution check", "hold", f"{why}; remaining commands cancelled")
            await self.bus.publish("responder/action", {"action": action, "route": rid, "item": item})

    # ---- perception updates and the visible re-plan -------------------------------------------

    async def on_world_change(self, data):
        await self.cancel_request("world changed")
        self.verified_route = None
        moved = ", ".join(data["moved_blocks"]) or "no blocks"
        was = self.state
        old = self.route["id"] if self.route else None
        self.state, self.route, self.request = IDLE, None, None
        self.replans = 0  # cells physics called unstable stay avoided: an aftershock rarely fixes them
        detail = f"Responder held, route {old} dropped" if old else "no active route"
        await self.log(f"{data['kind']} moved {moved}", "replanning",
                       f"{detail} (was {was}); waiting for the Scout to re-scan")
        if self.mission_args:
            await self.wait_for_scan(f"{data['kind']} moved {moved}")
            self.last_try = float("-inf")

    async def on_map(self, data):
        # The router subscribed to map/cells first (planner.start or start below), so it already merged it.
        self.map_version += 1
        if not self.waiting_scan or self.map_version <= self.scan_from_version:
            return
        now = self.clock()
        if now - self.last_try < REPLAN_EVERY_S:
            return
        self.last_try = now
        await self.propose(f"map re-scanned after {self.waiting_scan}")

    def on_hazards(self, data):
        self.hazards = list(data)

    def on_casualties(self, data):
        self.casualties = {c["id"]: c for c in data}

    # ---- offline mode (T15) -------------------------------------------------------------------

    async def on_link(self, data):
        was, self.online = self.online, data["online"]
        if was == self.online:
            return
        if not self.online:
            await self.log("status/link online:false", "offline",
                           "planning continues on this device: local A*, rule-based gate, local model for "
                           "goals; online review paused")
            return
        checks, self.offline_acts = self.offline_acts, []
        await self.log("status/link online:true", "online", f"link restored; re-checking {len(checks)} "
                       "route(s) chosen offline with gemini-4-argon")
        for c in checks:
            rid = c["route"]["id"]
            agree, why = await self.online_review(c["route"], c["hazards"])
            verdict = {True: "agrees", False: "disagrees", None: "skipped"}[agree]
            await self.log(f"offline route {rid} re-checked", f"recheck {verdict}", why or verdict,
                           model="gemini-4-argon" if agree is not None else MODEL)
            if agree is False and self.route and self.route["id"] == rid and self.state == EXECUTING:
                await self.refer(0.0, f"online re-check disagrees with offline route {rid}: {why}")

    async def on_command(self, data):
        """operator/command -> a mission. The local model (or keywords) only reads the goal."""
        text = data["text"]
        low = text.lower().strip()
        if low in ("stop", "hold"):
            await self.cancel_request("operator stopped the mission")
            self.verified_route = None
            self.state, self.route = IDLE, None
            return await self.log(f"operator: {text}", "hold", "operator stopped the mission; further dispatch held")
        if not self.places or self.interpret is None:
            return
        with self._step():  # the goal read counts toward ms_per_step: it is on the operator's path
            got = await asyncio.to_thread(self.interpret, text, list(self.places))
        place, model = got.get("place"), got.get("model", "keyword-stand-in")
        if place is None:
            return await self.log(f"operator: {text}", "ignored", "no known place in the command", model=model)
        goal = tuple(self.places[place])
        if low.startswith(("scan", "look", "check")):
            await self.log(f"operator: {text}", "relook", f"Scout scans {place}", model=model)
            return await self.goto(list(goal), f"operator asked to scan {place}")
        start = self.start_cell() if callable(self.start_cell) else self.start_cell
        if start is None:
            return await self.log(f"operator: {text}", "ignored", "Responder position unknown", model=model)
        item = got.get("item") or "water"
        why = got.get("why") or "goal read"
        await self.log(f"operator: {text}", "goal", f"{item} to {place}: {why}", model=model)
        return await self.mission(start, goal, goal_text=f"deliver {item.replace('_', ' ')} to {place}",
                                  item=item, casualty=None)


async def start(bus, router: RoutePlanner | None = None, *, budget=True, **kw) -> Loop:
    """Attach the T13 loop. Pass the T12 router from planner.start(bus) so the map is shared.

    With budget=True it also publishes status/budget every second; the task is `loop.task`, which the
    hub's lifespan cancels on shutdown. Pass places={name: cell} and start_cell to act on
    operator/command (goals read by the local model, planner.local_llm.interpret).
    """
    if router is None:
        router = RoutePlanner(bus)
        bus.subscribe("map/cells", router.update_map)
    if budget is True:
        from planner.budget import Budget
        budget = Budget(bus)
    if kw.get("places") and "interpret" not in kw:
        from planner import local_llm
        kw["interpret"] = local_llm.interpret
    lp = Loop(bus, router, budget=budget or None, **kw).attach()
    lp.task = asyncio.create_task(budget.run()) if budget else None
    return lp
