"""Injury triage and first-aid gate (Y3, perception lane).

Assesses casualty state from:
- Thermal (body temperature / thermal signature)
- Sound (acoustic detection, tapping, speech level)
- Camera check (posture: lying, sitting, standing, trapped under rubble)
- Voice dialogue answers (questions: hear, hurt, breathing, bleeding, move, walk, hurt_parts)

Uses coord/gem.py (gemini-4-argon or fast_subagent) with GEMINI_MODE=live.
When GEMINI_MODE=off (or no API key), runs deterministic offline triage rules.

Confidence scoring:
- If confidence >= 0.8 and recommended first-aid item is clear:
  emits gate/decision outcome="act", and triggers responder/action for the arm.
- If unsure (confidence < 0.8 or ambiguous injuries):
  sends a needs-human triage card to console via gate/request (kind="risky_move")
  with alternative first-aid supply options, and waits for gate/answer from the operator.
  Upon operator approval, triggers responder/action with the chosen first-aid step.

Provides public triage summary for Y6 paramedic report via TRIAGE.summary(cid).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from typing import Any

logger = logging.getLogger("perception.triage")

FEATURE = "triage"
ALLOWED_ITEMS = (
    "water",
    "first_aid_kit",
    "radio",
    "bandage",
    "splint",
    "thermal_blanket",
)
TRIAGE_LEVELS = ("immediate", "urgent", "delayed", "unknown")

try:
    from coord import gem
except ImportError:
    gem = None


def _gem():
    """Retrieve coord.gem if available."""
    try:
        from coord import gem as g
        return g
    except ImportError:
        return None


def get_mode() -> str:
    """Return current GEMINI_MODE (off | replay | live)."""
    env_mode = os.environ.get("GEMINI_MODE")
    if env_mode:
        m = env_mode.lower()
        g = _gem()
        if g and hasattr(g, "MODE"):
            g.MODE = m
        return m
    g = _gem()
    if g and hasattr(g, "MODE"):
        return str(g.MODE).lower()
    return "off"


def mark_stand_in(feature: str = FEATURE) -> None:
    """Register feature as running with a local stand-in."""
    g = _gem()
    if g and hasattr(g, "mark_stand_in"):
        g.mark_stand_in(feature)


def guide_summary(cid: str) -> dict[str, Any] | None:
    """Retrieve dialogue summary from Y5 voice.GUIDE if available without importing voice."""
    voice_mod = sys.modules.get("voice")
    if voice_mod is not None:
        guide = getattr(voice_mod, "GUIDE", None)
        if guide is not None and hasattr(guide, "summary"):
            try:
                res = guide.summary(cid)
                if isinstance(res, dict) and res.get("casualty") == cid:
                    return res
            except (RuntimeError, KeyError, AttributeError):
                pass
    return None


class TriageAssessment:
    """Result of injury triage evaluation for a casualty."""

    def __init__(
        self,
        casualty_id: str,
        triage_level: str,
        confidence: float,
        injuries: list[str],
        hurt_parts: list[str],
        recommended_item: str,
        options: list[dict[str, str]],
        needs_human: bool,
        rationale: str,
        source: str = "offline_rules",
        gate_request_id: str | None = None,
        route: str = "none",
    ):
        self.casualty_id = casualty_id
        self.triage_level = triage_level if triage_level in TRIAGE_LEVELS else "unknown"
        self.confidence = max(0.0, min(1.0, float(confidence)))
        self.injuries = list(injuries)
        self.hurt_parts = list(hurt_parts)
        self.recommended_item = recommended_item if recommended_item in ALLOWED_ITEMS else "first_aid_kit"
        self.options = list(options)
        self.needs_human = bool(needs_human)
        self.rationale = str(rationale)
        self.source = str(source)
        self.gate_request_id = gate_request_id
        self.route = str(route)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.casualty_id,
            "casualty": self.casualty_id,
            "triage_level": self.triage_level,
            "confidence": self.confidence,
            "injuries": self.injuries,
            "hurt_parts": self.hurt_parts,
            "recommended_action": self.recommended_item,
            "recommended_item": self.recommended_item,
            "options": self.options,
            "needs_human": self.needs_human,
            "rationale": self.rationale,
            "source": self.source,
            "gate_request_id": self.gate_request_id,
            "route": self.route,
        }


def offline_triage_rules(
    casualty: dict[str, Any],
    dialogue: dict[str, Any] | None = None,
    route: str = "none",
) -> TriageAssessment:
    """Deterministic rule-based clinical triage assessment for GEMINI_MODE=off."""
    cid = str(casualty.get("id", "c1"))
    clues = list(casualty.get("clues", []))
    vitals = casualty.get("vitals", {})
    rate = vitals.get("breathing_rate", 14)

    answers: dict[str, str] = {}
    hurt_parts: list[str] = []
    if dialogue and isinstance(dialogue, dict):
        raw_ans = dialogue.get("answers", {})
        if isinstance(raw_ans, dict):
            answers = {k: str(v).lower() for k, v in raw_ans.items()}
        raw_parts = dialogue.get("hurt_parts", [])
        if isinstance(raw_parts, list):
            hurt_parts = [str(p).lower() for p in raw_parts if isinstance(p, str)]

    # Clue detections
    has_thermal = "thermal" in clues
    has_sound = "sound" in clues
    has_camera = "camera" in clues

    injuries: list[str] = []
    options: list[dict[str, str]] = []

    # Evaluate signs & dialogue
    diff_breathing = answers.get("breathing") == "yes" or (rate is not None and (rate < 8 or rate > 28))
    bleeding_reported = answers.get("bleeding") == "yes"
    bleeding_unsure = answers.get("bleeding") == "unsure"
    cannot_move = answers.get("move") == "no"
    cannot_walk = answers.get("walk") == "no"
    has_limb_injury = any(p in hurt_parts for p in ("arm", "leg", "foot", "ankle", "knee", "shoulder"))

    if diff_breathing:
        injuries.append("respiratory_distress")
    if bleeding_reported:
        injuries.append("external_hemorrhage")
    elif bleeding_unsure:
        injuries.append("suspected_bleeding")
    if cannot_move or cannot_walk or has_limb_injury:
        injuries.append("limb_immobilization_or_fracture")

    # Determine Triage Level & Recommendation
    if diff_breathing or (bleeding_reported and cannot_move):
        triage_level = "immediate"
        recommended = "first_aid_kit"
        rationale = "Critical respiratory distress or complex trauma requiring emergency stabilization."
    elif bleeding_reported:
        triage_level = "urgent"
        recommended = "bandage"
        rationale = "Active bleeding reported; wound compression and sterile dressing needed."
    elif cannot_walk or cannot_move or has_limb_injury:
        triage_level = "urgent"
        recommended = "splint"
        rationale = "Limb fracture or severe mobility impairment; requires structural stabilization."
    elif not has_thermal and has_sound:
        triage_level = "urgent"
        recommended = "thermal_blanket"
        rationale = "Casualty detected by sound only; potential hypothermia or deep void entrapment."
    else:
        triage_level = "delayed"
        recommended = "water"
        rationale = "Stable vitals and mobility preserved; oral rehydration and monitoring advised."

    # Build options card for human gate
    options.append({
        "item": recommended,
        "label": f"Deliver {recommended.replace('_', ' ')}",
        "rationale": rationale,
    })
    for alt_item in ("bandage", "splint", "thermal_blanket", "water"):
        if alt_item != recommended:
            alt_rat = "Alternative supply for stabilization."
            if alt_item == "bandage":
                alt_rat = "Prophylactic compression for concealed cuts."
            elif alt_item == "splint":
                alt_rat = "Immobilize suspected secondary joint injury."
            elif alt_item == "thermal_blanket":
                alt_rat = "Prevent shock and body heat loss in damp collapse."
            elif alt_item == "water":
                alt_rat = "Provide clean drinking water if casualty is alert."
            options.append({
                "item": alt_item,
                "label": f"Deliver {alt_item.replace('_', ' ')}",
                "rationale": alt_rat,
            })
        if len(options) >= 3:
            break

    # Confidence calculation
    conf = float(casualty.get("confidence", 0.7))
    if not has_camera:
        # Camera visual check absent: slight confidence penalty
        conf = min(conf, 0.78)
    if triage_level == "immediate":
        # Immediate life-threat requires human doctor / operator confirmation
        needs_human = True
    elif not answers or all(v in ("none", "unknown") for v in answers.values()):
        # Dialogue unavailable or unanswered: high uncertainty
        conf = min(conf, 0.65)
        needs_human = True
    elif bleeding_unsure or len(injuries) > 1:
        # Ambiguous symptoms or multiple concurrent trauma: requires operator judgment
        conf = min(conf, 0.72)
        needs_human = True
    elif conf >= 0.8:
        needs_human = False
    else:
        needs_human = conf < 0.8

    req_id = f"g_triage_{cid}" if needs_human else None
    return TriageAssessment(
        casualty_id=cid,
        triage_level=triage_level,
        confidence=conf,
        injuries=injuries or ["unspecified_collapse_injury"],
        hurt_parts=hurt_parts,
        recommended_item=recommended,
        options=options,
        needs_human=needs_human,
        rationale=rationale,
        source="offline_rules",
        gate_request_id=req_id,
        route=route,
    )


def extract_json_payload(text: str) -> dict[str, Any] | None:
    """Extract JSON object from LLM response text."""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except (ValueError, json.JSONDecodeError):
            pass
    m2 = re.search(r"(\{[\s\S]*\})", text)
    if m2:
        try:
            return json.loads(m2.group(1))
        except (ValueError, json.JSONDecodeError):
            pass
    return None


def gemini_triage(
    casualty: dict[str, Any],
    dialogue: dict[str, Any] | None = None,
    route: str = "none",
) -> TriageAssessment:
    """Perform LLM injury triage reasoning via coord/gem.py."""
    g = _gem()
    if g is None or get_mode() == "off":
        mark_stand_in(FEATURE)
        return offline_triage_rules(casualty, dialogue, route)

    cid = str(casualty.get("id", "c1"))
    prompt = (
        f"Search and rescue triage evaluation for collapsed structure casualty.\n"
        f"Casualty ID: {cid}\n"
        f"Position: {casualty.get('pos')}\n"
        f"Sensor clues: {casualty.get('clues', [])}\n"
        f"Detection confidence: {casualty.get('confidence')}\n"
        f"Vitals: {casualty.get('vitals', {})}\n"
        f"Self-reported dialogue: {dialogue or 'None'}\n\n"
        f"Allowed responder items: {list(ALLOWED_ITEMS)}\n"
        f"Assess triage priority and determine if human gate review is required.\n"
        f"Output JSON ONLY with keys:\n"
        f'{{"triage_level": "immediate"|"urgent"|"delayed"|"unknown",\n'
        f' "injuries": ["string"],\n'
        f' "hurt_parts": ["string"],\n'
        f' "recommended_item": "water"|"first_aid_kit"|"radio"|"bandage"|"splint"|"thermal_blanket",\n'
        f' "options": [{{"item": "item_name", "label": "description", "rationale": "reason"}}],\n'
        f' "confidence": float between 0.0 and 1.0,\n'
        f' "needs_human": boolean,\n'
        f' "rationale": "one-line medical reasoning"}}\n'
    )

    try:
        reply = g.ask("lead_reasoning", prompt, thinking="medium", feature=FEATURE)
        parsed = extract_json_payload(reply)
        if parsed and isinstance(parsed, dict):
            lvl = str(parsed.get("triage_level", "urgent")).lower()
            rec = str(parsed.get("recommended_item", "first_aid_kit")).lower()
            conf = float(parsed.get("confidence", 0.75))
            nh = bool(parsed.get("needs_human", conf < 0.8))
            opts = list(parsed.get("options", []))
            req_id = f"g_triage_{cid}" if nh else None
            return TriageAssessment(
                casualty_id=cid,
                triage_level=lvl,
                confidence=conf,
                injuries=list(parsed.get("injuries", [])),
                hurt_parts=list(parsed.get("hurt_parts", [])),
                recommended_item=rec if rec in ALLOWED_ITEMS else "first_aid_kit",
                options=opts or [{"item": rec, "label": f"Deliver {rec}", "rationale": "Gemini assessment"}],
                needs_human=nh,
                rationale=str(parsed.get("rationale", "Gemini triage assessment")),
                source="gemini-4-argon",
                gate_request_id=req_id,
                route=route,
            )
    except (RuntimeError, KeyError, OSError, ValueError) as err:
        logger.warning("Gemini triage call failed or returned unparseable text: %s; falling back to offline rules.", err)

    mark_stand_in(FEATURE)
    return offline_triage_rules(casualty, dialogue, route)


class Triager:
    """Manages casualty triage assessments and human gate approvals."""

    def __init__(self, dialogue_reader=None):
        self.dialogue_reader = dialogue_reader or guide_summary
        self.assessments: dict[str, TriageAssessment] = {}
        self.pending_gates: dict[str, TriageAssessment] = {}  # gate_request_id -> assessment
        self.bus = None

    def assess(
        self,
        casualty: dict[str, Any],
        dialogue: dict[str, Any] | None = None,
        route: str = "none",
    ) -> TriageAssessment:
        """Run injury triage evaluation and store assessment."""
        cid = str(casualty.get("id", "c1"))
        diag = dialogue if dialogue is not None else self.dialogue_reader(cid)
        mode = get_mode()
        if mode == "off":
            mark_stand_in(FEATURE)
            res = offline_triage_rules(casualty, diag, route=route)
        else:
            res = gemini_triage(casualty, diag, route=route)

        self.assessments[cid] = res
        if res.needs_human and res.gate_request_id:
            self.pending_gates[res.gate_request_id] = res
        return res

    def summary(self, cid: str) -> dict[str, Any] | None:
        """Provide factual triage summary for Y6 remote paramedic report."""
        res = self.assessments.get(cid)
        if res is None:
            return None
        return res.to_dict()

    async def on_casualties(self, casualties_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Process map/casualties message, publishing gate requests or decisions as required."""
        events = []
        for cas in casualties_list:
            cid = cas.get("id")
            if not cid:
                continue
            assessment = self.assess(cas)
            triage_msg = {
                "id": assessment.casualty_id,
                "injuries": assessment.injuries,
                "recommended_action": assessment.recommended_item,
            }
            events.append(("casualty/triage", triage_msg))
            if self.bus and hasattr(self.bus, "publish"):
                try:
                    await self.bus.publish("casualty/triage", triage_msg)
                except (KeyError, ValueError, RuntimeError, TypeError, AttributeError) as exc:
                    # Hub may reject unregistered topics under strict validation
                    logger.debug("casualty/triage publish skipped on bus: %s", exc)

            if assessment.needs_human and assessment.gate_request_id:
                # Format options into card summary
                opts_summary = ", ".join(f"{opt['item']}: {opt['label']}" for opt in assessment.options[:3])
                gate_req = {
                    "id": assessment.gate_request_id,
                    "kind": "risky_move",
                    "summary": f"Triage review for {cid}: {opts_summary}",
                    "route": assessment.route,
                }
                gate_dec = {
                    "id": assessment.gate_request_id,
                    "outcome": "refer",
                    "confidence": assessment.confidence,
                    "reason": assessment.rationale,
                }
                events.append(("gate/request", gate_req))
                events.append(("gate/decision", gate_dec))
                if self.bus and hasattr(self.bus, "publish"):
                    await self.bus.publish("gate/request", gate_req)
                    await self.bus.publish("gate/decision", gate_dec)
            else:
                # Autonomous approval based on high confidence
                dec_id = f"d_triage_{cid}"
                gate_dec = {
                    "id": dec_id,
                    "outcome": "act",
                    "confidence": assessment.confidence,
                    "reason": assessment.rationale,
                }
                resp_act = {
                    "action": "place_supply",
                    "route": assessment.route,
                    "item": assessment.recommended_item,
                }
                events.append(("gate/decision", gate_dec))
                events.append(("responder/action", resp_act))
                if self.bus and hasattr(self.bus, "publish"):
                    await self.bus.publish("gate/decision", gate_dec)
                    await self.bus.publish("responder/action", resp_act)
        return events

    async def on_answer(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Handle operator gate/answer. If approved, emit responder/action for chosen item."""
        req_id = data.get("id")
        approved = data.get("approved") is True
        assessment = self.pending_gates.get(req_id)
        if not assessment:
            return None

        cid = assessment.casualty_id
        if approved:
            item = assessment.recommended_item
            action = {
                "action": "place_supply",
                "route": assessment.route,
                "item": item,
            }
            log_entry = {
                "t": time.monotonic(),
                "perception": f"triage approved for {cid}, place_supply {item}",
                "model": "triage_gate",
                "physics": "human_approved",
                "outcome": "act",
                "reason": f"Operator approved triage card {req_id} for {cid}: {item}",
            }
            if self.bus and hasattr(self.bus, "publish"):
                await self.bus.publish("responder/action", action)
                await self.bus.publish("log/decision", log_entry)
            del self.pending_gates[req_id]
            return action

        # Denied
        log_entry = {
            "t": time.monotonic(),
            "perception": f"triage denied for {cid}",
            "model": "triage_gate",
            "physics": "human_denied",
            "outcome": "refer",
            "reason": f"Operator denied triage card {req_id} for {cid}",
        }
        if self.bus and hasattr(self.bus, "publish"):
            await self.bus.publish("log/decision", log_entry)
        del self.pending_gates[req_id]
        return None

    def attach(self, bus: Any) -> Triager:
        """Attach subscriptions to the bus."""
        self.bus = bus
        if bus and hasattr(bus, "subscribe"):
            bus.subscribe("map/casualties", lambda data: self.on_casualties(data))
            bus.subscribe("gate/answer", lambda data: self.on_answer(data))
        return self


# Global singleton
TRIAGE = Triager()


def triage_summary(cid: str) -> dict[str, Any] | None:
    """Public helper for other lanes to retrieve triage summary without importing."""
    return TRIAGE.summary(cid)
