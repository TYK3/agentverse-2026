"""T16: collect a factual handover, render Markdown, and publish/save it."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import html
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from planner.paramedic import (
    ParamedicReports,
    is_report_command,
    render_paramedic_markdown,
)

REPORTS = Path(__file__).resolve().parents[1] / "reports"


def _pick(data, keys):
    return {key: copy.deepcopy(data[key]) for key in keys if key in data}


def _text(value):
    """Render plain event text without allowing HTML or Markdown image/link markup."""
    text = html.escape(str(value)).replace("\n", " ").replace("\r", " ")
    return re.sub(r"([\\`*_[\]#!|])", r"\\\1", text)


def render_markdown(report):
    """The same factual renderer is used for templates and optional model drafts."""
    stats = report["map"]
    lines = ["# AFTERLIGHT handover", "", _text(report["summary"]), "",
             f"Source: {_text(report['source'])}. Vitals are simulated; hazards are estimates.", "",
             (f"Map: {stats['seen']} seen, {stats['inferred']} inferred, {stats['unknown']} explicit unknown; "
              f"{stats['occupied']} occupied. Unlisted cells remain unknown."), "", "## Casualties"]
    for casualty in report["casualties"]:
        vitals = casualty.get("vitals", {})
        vital_text = f"; simulated breathing rate {vitals['breathing_rate']}" if "breathing_rate" in vitals else ""
        lines.append(f"- {_text(casualty['id'])}: {_text(casualty['pos'])}, confidence "
                     f"{casualty['confidence']:.2f}; clues {_text(', '.join(casualty['clues']))}{vital_text}.")
    if not report["casualties"]:
        lines.append("- No casualty observation received.")
    lines.extend(["", "## Hazards (estimate)"])
    for phase in ("before", "after"):
        hazards = report["hazards"][phase]
        detail = "; ".join(f"{h['cell']} {h['status']}: {h['why']}" for h in hazards) or "none reported"
        lines.append(f"- {phase.title()} (estimate): {_text(detail)}.")
    lines.extend(["", "## Routes and re-plans"])
    for route in report["routes"]:
        verdict = route.get("physics", {})
        checked = "verified" if verdict.get("ok") is True else "rejected" if verdict else "pending physics"
        lines.append(f"- {_text(route['id'])}: {len(route['cells'])} cells, {_text(route['goal'])}; "
                     f"{checked}, {_text(route['model'])}.")
    for event in report["replans"]:
        lines.append(f"- {event['t']:.2f}s: {_text(event['perception'])}; {_text(event['reason'])}.")
    if not report["routes"] and not report["replans"]:
        lines.append("- No route or re-plan recorded.")
    lines.extend(["", "## Actions and supplies"])
    for action in report["actions"]:
        lines.append(f"- {action['t']:.2f}s: {_text(action['action'])} {_text(action['item'])} "
                     f"on {_text(action['route'])} ({_text(action['status'])}).")
    if not report["actions"]:
        lines.append("- No Responder action commanded.")
    for delivery in report["supplies_delivered"]:
        lines.append(f"- Simulated delivery confirmed: {_text(delivery['item'])} at {_text(delivery['pos'])}, "
                     f"{delivery['t']:.2f}s (sim placement log).")
    if not report["supplies_delivered"]:
        lines.append("Confirmed supplies delivered: none recorded; action commands do not confirm delivery.")
    lines.extend(["", "## Human approvals"])
    for request in report["approvals"]:
        answers = "; ".join(f"{a['t']:.2f}s {a['by']}: {'approved' if a['approved'] else 'denied'}"
                            for a in request["answers"]) or "no answer"
        lines.append(f"- {_text(request['id'])}, {request['requested_at']:.2f}s, {_text(request['kind'])}, "
                     f"{_text(request['route'])}: {_text(request['summary'])}; {_text(answers)}; "
                     f"{_text(request['status'])}.")
    if not report["approvals"]:
        lines.append("- No approval requests recorded.")
    lines.extend(render_paramedic_markdown(report.get("paramedic_reports", []), _text))
    lines.extend(["", "## Open risks"])
    lines.extend(f"- {_text(risk)}" for risk in report["open_risks"])
    return "\n".join(lines) + "\n"


class ReportCollector:
    """One collector per run. Only allowlisted, non-image event fields are retained."""

    def __init__(self, bus, *, output_dir=REPORTS, clock=time.monotonic, gem=None, model_timeout=8,
                 dialogue_summary=None):
        self.bus, self.output_dir, self.clock = bus, Path(output_dir), clock
        self.t0 = clock()
        self.paramedics = ParamedicReports(self._t, dialogue_summary)
        self._sim_route = None
        self.cells = {}
        self.res = None
        self.casualties = []
        self.hazards_before = None
        self.hazards_after = []
        self.routes = {}
        self.replans = []
        self.actions = []
        self.sim_action_results = []
        self.deliveries = []
        self.approvals = {}
        self.unmatched_answers = []
        self._lock = asyncio.Lock()
        self.gem = gem
        self.model_timeout = model_timeout
        self._model_attempted = False
        self._draft = None
        self._draft_key = None
        self._model_note = "plain template; model stand-in"

    def attach(self):
        for topic, fn in (("map/cells", self.on_map), ("map/casualties", self.on_casualties),
                          ("map/hazards", self.on_hazards), ("route/proposed", self.on_route),
                          ("route/verified", self.on_verified), ("world/change", self.on_world_change),
                          ("log/decision", self.on_log), ("responder/action", self.on_action),
                          ("gate/request", self.on_request), ("gate/answer", self.on_answer),
                          ("operator/command", self.on_command)):
            self.bus.subscribe(topic, fn)
        return self

    def _t(self):
        return round(max(0, self.clock() - self.t0), 3)

    def on_map(self, data):
        if self.res != data["res"]:
            self.cells.clear()
            self.res = data["res"]
        for record in data["cells"]:
            self.cells[tuple(record["cell"])] = _pick(record, ("state", "occupied"))

    def on_casualties(self, data):
        self.casualties = []
        for record in data:
            casualty = _pick(record, ("id", "pos", "confidence", "clues"))
            vitals = record.get("vitals", {})
            casualty["vitals"] = {**_pick(vitals, ("breathing_rate",)), "simulated": True}
            self.casualties.append(casualty)
        self.paramedics.observe(self.casualties)

    def on_hazards(self, data):
        hazards = [{**_pick(h, ("cell", "status", "why")), "estimate": True} for h in data]
        if self.hazards_before is None:
            self.hazards_before = copy.deepcopy(hazards)
        self.hazards_after = hazards

    def on_route(self, data):
        self.routes[data["id"]] = _pick(data, ("id", "robot", "cells", "goal", "model"))

    def on_verified(self, data):
        if data["id"] in self.routes:
            self.routes[data["id"]]["physics"] = _pick(data, ("ok", "unstable_cells", "detail"))

    def on_world_change(self, data):
        self.replans.append({"t": data["t"], "perception": data["kind"],
                             "reason": f"moved blocks: {', '.join(data['moved_blocks'])}"})

    def on_log(self, data):
        if data["model"] == "sim" and data["physics"] == "mujoco":
            move = re.search(r", move (\S+)$", data.get("perception", ""))
            result_route = (move[1] if move[1] in self.routes else None) if move else self._sim_route
            if move and data["outcome"] in ("act", "done"):
                self._sim_route = move[1] if move[1] in self.routes else None
            elif move and data["outcome"] == "refused":
                self._sim_route = None  # subsequent item logs have no dependable active-route attribution
            if result_route and data.get("perception", "").startswith("responder at ["):
                self.sim_action_results.append({**_pick(data, ("t", "perception", "outcome", "reason")),
                                                "route": result_route, "simulated": True})
        if data["model"] == "sim" and data["physics"] == "mujoco" and data["outcome"] == "done":
            placed = re.fullmatch(r"placed (water|first_aid_kit|radio|bandage|splint|thermal_blanket) "
                                  r"at \[(-?\d+(?:\.\d+)?), (-?\d+(?:\.\d+)?)\]",
                                  data["reason"])
            if placed and data["perception"].endswith(f", place_supply {placed[1]}"):
                item, x, y = placed.groups()
                pending = [a for a in self.actions if a["action"] == "place_supply"
                           and a["item"] == item and a["status"].startswith("commanded")]
                if self._sim_route is not None:
                    pending = [a for a in pending if a["route"] == self._sim_route]
                # Repeated supplies for different casualties cannot be attributed by item alone.
                command = pending[0] if len({a["route"] for a in pending}) == 1 else None
                delivery = {"item": item, "pos": [float(x), float(y)], "t": data["t"], "simulated": True,
                            "route": command["route"] if command else self._sim_route}
                if not any(d["item"] == item and d["t"] == data["t"] and d["pos"] == delivery["pos"]
                           for d in self.deliveries):
                    self.deliveries.append(delivery)
                    if command:
                        command["status"] = "simulated placement confirmed by sim log"
        if data["outcome"] == "replanning" or "re-plan" in data["perception"]:
            self.replans.append(_pick(data, ("t", "perception", "reason")))
        if data["outcome"] == "hold":
            match = re.fullmatch(r"gate (g\d+)", data["perception"])
            if match and match[1] in self.approvals:
                self.approvals[match[1]]["status"] = data["reason"]

    def on_action(self, data):
        self.actions.append({**_pick(data, ("action", "route", "item", "block")), "t": self._t(),
                             "status": "commanded; completion unconfirmed"})

    def on_request(self, data):
        if data["id"] in self.approvals:
            return  # replaying a request must not erase its answer history
        early = [answer for answer in self.unmatched_answers if answer["id"] == data["id"]]
        self.unmatched_answers = [answer for answer in self.unmatched_answers if answer["id"] != data["id"]]
        self.approvals[data["id"]] = {**_pick(data, ("id", "kind", "summary", "route")),
                                      "requested_at": self._t(), "status": "pending", "answers": []}
        for answer in early:
            self.approvals[data["id"]]["answers"].append(_pick(answer, ("approved", "by", "t")))
        if early:
            self.approvals[data["id"]]["status"] = "operator approved" if early[0]["approved"] else "operator denied"

    def on_answer(self, data):
        answer = {"approved": data["approved"] is True, "by": data.get("by", "unspecified"), "t": self._t()}
        request = self.approvals.get(data["id"])
        if request is None:
            self.unmatched_answers.append({"id": data["id"], **answer})
            return
        request["answers"].append(answer)
        if request["status"] == "pending":
            request["status"] = "operator approved" if data["approved"] is True else "operator denied"

    async def on_command(self, data):
        if is_report_command(data["text"]):
            await self.generate()

    def snapshot(self):
        stats = {state: sum(r["state"] == state for r in self.cells.values())
                 for state in ("seen", "inferred", "unknown")}
        stats["occupied"] = sum(r["occupied"] for r in self.cells.values())
        stats["res"] = self.res
        risks = ["Hazards are simulated estimates; vitals are simulated.",
                 "Only seen, free cells are confirmed for route planning; unlisted cells remain unknown.",
                 "Responder commands alone do not confirm delivery; only sim placement logs count as simulated completion."]
        if any(r["status"] == "pending" for r in self.approvals.values()):
            risks.append("Human approval requests are still pending.")
        if self.unmatched_answers:
            risks.append("Unmatched approval answers were received; they grant no permission.")
        report = copy.deepcopy({
            "summary": f"{len(self.casualties)} casualty observations; {len(self.routes)} routes; "
                       f"{len(self.replans)} world-change/re-plan records; {len(self.approvals)} approval requests.",
            "map": stats, "casualties": self.casualties,
            "hazards": {"before": self.hazards_before or [], "after": self.hazards_after},
            "routes": list(self.routes.values()), "replans": self.replans, "actions": self.actions,
            "sim_action_results": self.sim_action_results,
            "supplies_delivered": self.deliveries, "approvals": list(self.approvals.values()),
            "unmatched_answers": self.unmatched_answers, "open_risks": risks,
            "source": "plain template; model stand-in",
        })
        report["paramedic_reports"] = self.paramedics.build(report)
        return report

    @staticmethod
    def _key(report):
        return hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()

    async def _draft_once(self, report):
        if self._model_attempted:
            return
        self._model_attempted = True  # before awaiting: concurrent requests cannot spend twice
        gem = self.gem
        if gem is None:
            try:
                from coord import gem
            except ImportError:
                self._model_note = "plain template; model wrapper unavailable"
                return
            self.gem = gem
        if getattr(gem, "MODE", "off") == "off":
            gem.mark_stand_in("handover_report")
            self._model_note = "plain template; GEMINI_MODE=off stand-in"
            return
        sections = ("summary", "casualties", "hazards", "actions", "approvals", "open_risks")
        prompt = (
            "Draft a concise rescue handover as JSON only with sections summary, casualties, hazards, "
            "actions, approvals, open_risks. Rewrite only summary (maximum 1200 characters). Copy all "
            "other sections exactly from the recorded facts below. Vitals are simulated, hazards are "
            "estimates, commands do not prove delivery. Do not invent facts or include images, URLs or "
            "personal identifiers.\n" + json.dumps(report)
        )
        try:
            reply = await asyncio.wait_for(asyncio.to_thread(
                gem.ask, "fast_subagent", prompt, thinking="low", feature="handover_report"), self.model_timeout)
            reply = re.sub(r"^```(?:json)?\s*|\s*```$", "", reply.strip())
            draft = json.loads(reply)
            if not isinstance(draft, dict) or any(k not in draft for k in sections):
                raise ValueError("missing report sections")
            if any(draft[k] != report[k] for k in sections if k != "summary"):
                raise ValueError("model changed recorded facts")
            summary = draft["summary"]
            if (not isinstance(summary, str) or not summary.strip() or len(summary) > 1200
                    or re.search(r"https?://|data:|base64|[A-Za-z0-9+/]{100,}", summary, re.IGNORECASE)):
                raise ValueError("invalid report summary")
            self._draft, self._draft_key = summary, self._key(report)
            self._model_note = "gemini-3.8-flash draft; recorded facts retained"
        except Exception as error:  # noqa: BLE001 -- every model failure falls back to the factual template
            gem.mark_stand_in("handover_report")
            self._model_note = f"plain template; model draft unavailable ({type(error).__name__})"

    async def generate(self):
        async with self._lock:
            report = self.snapshot()
            await self._draft_once(report)
            report = self.snapshot()  # include events received while the draft was running
            if self._draft is not None and self._key(report) == self._draft_key:
                report["summary"] = self._draft
                report["source"] = self._model_note
            else:
                report["source"] = ("plain template; model draft predates current events"
                                    if self._draft else self._model_note)
            markdown = render_markdown(report)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
            path = self.output_dir / f"handover_{stamp}.md"
            path.write_text(markdown, encoding="utf-8")
            payload = {"json": report, "markdown": markdown}
        await self.bus.publish("report/handover", payload)
        return {**payload, "path": path}


async def start(bus, **kwargs):
    return ReportCollector(bus, **kwargs).attach()
