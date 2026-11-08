"""Y6: factual per-casualty handovers for a remote paramedic, available offline."""

from __future__ import annotations

import copy
import sys

REPORT_COMMANDS = {"report", "handover report", "generate report", "paramedic report", "remote paramedic report"}
QUESTIONS = ("hear", "hurt", "breathing", "bleeding", "move", "walk")
QUESTION_LABELS = {"hear": "Can hear the robot", "hurt": "Pain reported", "breathing": "Difficulty breathing",
                   "bleeding": "Bleeding reported", "move": "Can move arms and legs", "walk": "Can stand and walk"}
ANSWERS = {"yes", "no", "unsure", "none"}
BODY_PARTS = {"head", "neck", "back", "spine", "chest", "stomach", "belly", "arm", "hand", "leg",
              "knee", "foot", "ankle", "hip", "shoulder", "face", "eye", "ribs"}


def is_report_command(text):
    return text.strip().casefold() in REPORT_COMMANDS


def guide_summary(cid):
    """Read Y5's public API only if voice is already loaded; never start audio or a model."""
    guide = getattr(sys.modules.get("voice"), "GUIDE", None)
    return guide.summary(cid) if guide is not None else None


class ParamedicReports:
    def __init__(self, clock, dialogue_summary=None):
        self.clock = clock
        self.dialogue_summary = dialogue_summary or guide_summary
        self.observations = {}
        self.current = set()

    def observe(self, casualties):
        self.current = {c["id"] for c in casualties}
        for casualty in casualties:
            self.observations[casualty["id"]] = {
                "observation": copy.deepcopy(casualty), "t": self.clock(),
            }

    def _dialogue(self, cid):
        try:
            summary = self.dialogue_summary(cid)
        except Exception:  # noqa: BLE001 -- optional dialogue must not prevent the factual handover
            summary = None
        if not isinstance(summary, dict) or summary.get("casualty") != cid:
            return None
        return summary

    def build(self, facts):
        """Detection confidence applies only to location; no invented injury/vital confidence."""
        reports = []
        routes = {}
        for route in facts["routes"]:
            matches = [cid for cid in self.observations if route["goal"].endswith(" to " + cid)]
            if len(matches) == 1:
                routes[route["id"]] = matches[0]
        for cid, record in self.observations.items():
            cas, observed_at = record["observation"], record["t"]
            summary = self._dialogue(cid)
            answers = summary.get("answers", {}) if summary else {}
            if not isinstance(answers, dict):
                answers = {}
            responses = [{"question": q, "question_text": QUESTION_LABELS[q],
                          "answer": answers[q] if isinstance(answers.get(q), str)
                          and answers[q] in ANSWERS else "unknown",
                          "source": "self_reported"} for q in QUESTIONS]
            hurt = next(r["answer"] for r in responses if r["question"] == "hurt")
            parts = summary.get("hurt_parts", []) if summary else []
            parts = sorted({p for p in parts if isinstance(p, str) and p in BODY_PARTS}) if isinstance(parts, list) else []
            owned = {rid for rid, owner in routes.items() if owner == cid}
            actions = [copy.deepcopy(a) for a in facts["actions"] if a["route"] in owned]
            results = [copy.deepcopy(r) for r in facts.get("sim_action_results", []) if r["route"] in owned]
            deliveries = [copy.deepcopy(d) for d in facts["supplies_delivered"] if d.get("route") in owned]
            approvals = [copy.deepcopy(a) for a in facts["approvals"] if a["route"] in owned]
            unknowns = [f"{r['question']}: no answer recorded" for r in responses if r["answer"] == "unknown"]
            if not summary:
                unknowns.append("Casualty dialogue unavailable; no injury diagnosis has been made.")
            rate = cas.get("vitals", {}).get("breathing_rate")
            if rate is None:
                unknowns.append("Breathing rate not observed.")
            if cid not in self.current:
                unknowns.append("Absent from the latest casualty list; location is the last observation.")
            if any(a["status"].startswith("commanded") for a in actions):
                unknowns.append("Some action commands remain unconfirmed; no completion is inferred for them.")
            if any(a["status"] == "pending" for a in approvals):
                unknowns.append("Human approval is still pending.")
            reports.append({
                "id": cid,
                "location": {"pos": copy.deepcopy(cas["pos"]), "frame": "scene", "units": "m",
                             "observed_at": observed_at, "currently_reported": cid in self.current,
                             "estimate": True},
                "vitals": {"breathing_rate": rate, "simulated": True,
                           "observed_at": observed_at, "source": "simulated perception"},
                "confidence": {"location": cas["confidence"], "injuries": None, "vitals": None,
                               "note": "Detection confidence is not medical certainty."},
                "clues": list(cas.get("clues", [])),
                "injuries": {"status": "reported" if hurt == "yes" or parts else
                             "none_reported" if hurt == "no" else "unknown",
                             "hurt_parts": parts, "source": "self_reported", "diagnosis": None},
                "responses": responses,
                "dialogue_available": summary is not None,
                "actions": actions, "action_results": results, "supplies_delivered": deliveries, "approvals": approvals,
                "unknowns": unknowns,
                "note": "Remote observations and self-reports for human review; vitals are simulated. "
                        "No diagnosis or treatment completion is inferred.",
            })
        return reports


def render_paramedic_markdown(reports, escape):
    lines = ["", "## Remote paramedic reports"]
    if not reports:
        return lines + ["No casualty observations received; no patient report can be inferred."]
    for report in reports:
        loc, vitals, injuries = report["location"], report["vitals"], report["injuries"]
        lines += ["", f"### Casualty {escape(report['id'])}", escape(report["note"]),
                  (f"- Location estimate: {escape(loc['pos'])} m (scene frame), "
                   f"observed at {loc['observed_at']:.2f}s; detection confidence {report['confidence']['location']:.2f}."),
                  f"- Clues: {escape(', '.join(report['clues']))}.",
                  (f"- Breathing rate: {escape(vitals['breathing_rate']) if vitals['breathing_rate'] is not None else 'unknown'} "
                   "(simulated; no clinical confidence supplied)."),
                  (f"- Injuries: {escape(injuries['status'].replace('_', ' '))}; self-reported locations: "
                   f"{escape(', '.join(injuries['hurt_parts'])) or 'none recorded'}; diagnosis unknown.")]
        for response in report["responses"]:
            answer = {"none": "no response recorded", "unknown": "not asked or unavailable"}.get(
                response["answer"], response["answer"])
            lines.append(f"- {escape(response['question_text'])}: {escape(answer)} (self-reported).")
        for action in report["actions"]:
            block = f", found material {escape(action['block'])}" if action.get("block") else ""
            lines.append(f"- Action: {escape(action['action'])} {escape(action['item'])} "
                         f"on {escape(action['route'])}{block}: {escape(action['status'])}.")
        if not report["actions"]:
            lines.append("- Actions: none associated with this casualty.")
        for result in report["action_results"]:
            lines.append(f"- Simulated action result {result['t']:.2f}s on {escape(result['route'])}: "
                         f"{escape(result['outcome'])}; {escape(result['reason'])}.")
        for delivery in report["supplies_delivered"]:
            lines.append(f"- Confirmed simulated delivery: {escape(delivery['item'])} "
                         f"at {escape(delivery['pos'])}, {delivery['t']:.2f}s.")
        for approval in report["approvals"]:
            lines.append(f"- Human gate {escape(approval['id'])}: {escape(approval['status'])}.")
            for answer in approval["answers"]:
                decision = "approved" if answer["approved"] else "denied"
                lines.append(f"  - {answer['t']:.2f}s: {escape(answer['by'])} {decision}.")
        lines += [f"- Unknown: {escape(note)}" for note in report["unknowns"]]
    return lines
