"""Spoken approval (ref G7): the operator says "approve" or "hold" to answer the planner's gate.

The planner already holds the Responder's next physical move until the matching `gate/answer`
(planner/loop.py on_answer). This lets the operator give that answer by voice:
- on `gate/request` the request becomes pending (one at a time, the planner's latest);
- `heard(transcript)` (called with each push-to-talk transcript, before it is read as a command)
  decides approve / hold and publishes `gate/answer {"id", "approved", "by": "operator"}`:
  "hold" sends approved: false, which the planner turns into "approval refused; Responder idle";
- the decision comes from Gemini (`fast_router`, only through coord/gem.py), and is checked against
  the words actually said: Gemini alone never approves. Approve needs both Gemini and an approval word
  with no hold word in the transcript; hold wins if either says hold (holding still is the safe side);
- GEMINI_MODE=off (or no coord/gem.py): no spoken answers; the console's approve button is the way;
- after TIMEOUT_S with no answer the pending request is dropped: nothing is sent, the robot stays
  held, and the planner's own deadline expires the request;
- a console button answer clears the pending request, so a request is never answered twice.
"""

from __future__ import annotations

import json
import re
import sys
import time

TIMEOUT_S = 60.0                 # matches the planner's approval window (T14)
FEATURE = "spoken_approval"
MODEL = "fast_router"

APPROVE_WORDS = ("approve", "approved", "yes", "go ahead", "confirm", "confirmed", "proceed", "do it",
                 "affirmative", "go")
HOLD_WORDS = ("hold", "wait", "stop", "no", "not", "don't", "dont", "do not", "cancel", "abort", "negative",
              "deny", "denied", "reject", "freeze", "not yet")

PROMPT = """You answer a rescue robot's approval gate from what the operator just said.
Request: {summary} (kind {kind}, route {route}).
The operator said: "{heard}"
Reply with JSON only: {{"decision": "approve"}} if they clearly approve this request, {{"decision": "hold"}} if
they want the robot to wait, stop or not do it, {{"decision": "none"}} if it is not an answer to the request."""

_ACTIVE = None


def _gem():
    try:
        from coord import gem
    except ImportError:
        return None
    return gem


def _phrases(text):
    return " " + re.sub(r"[^a-z' ]+", " ", text.lower()).strip() + " "


def local_decision(text):
    """"hold", "approve" or None from the words said; any hold word wins."""
    said = _phrases(text)
    if any(f" {w} " in said for w in HOLD_WORDS):
        return "hold"
    if any(f" {w} " in said for w in APPROVE_WORDS):
        return "approve"
    return None


def parse_model(text):
    """The decision in Gemini's JSON reply, or None if it is not one of approve / hold / none."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        decision = json.loads(match.group(0)).get("decision") if match else None
    except (ValueError, AttributeError):
        return None
    return decision if decision in ("approve", "hold") else None


class SpokenApproval:
    def __init__(self, bus, timeout_s=TIMEOUT_S, clock=time.monotonic, gem=None):
        self.bus = bus
        self.timeout_s = timeout_s
        self.clock = clock
        self.gem = gem if gem is not None else _gem()
        self.pending = None           # (gate/request data, deadline)
        self.log = []                 # (event, detail) for tests and the operator console log

    # ---- bus -----------------------------------------------------------------------------
    def on_request(self, data):
        self.pending = (dict(data), self.clock() + self.timeout_s)
        self.log.append(("pending", data.get("id")))

    def on_answer(self, data):
        if self.pending and data.get("id") == self.pending[0].get("id"):
            self.pending = None       # answered (button or voice): never answer twice
            self.log.append(("answered", data.get("id")))

    # ---- speech ----------------------------------------------------------------------------
    def _model(self, heard, request):
        gem = self.gem
        prompt = PROMPT.format(heard=heard.replace('"', "'"), summary=request.get("summary", ""),
                               kind=request.get("kind", ""), route=request.get("route", ""))
        try:
            result = gem.ask_with_receipt(MODEL, prompt, thinking="low", feature=FEATURE,
                                          route=request.get("route") or None)
        except Exception as e:  # noqa: BLE001  (GeminiOff, cap, network: fall back to the button, never guess)
            if type(e).__name__ == "GeminiOff":
                self._stand_in("GEMINI_MODE=off: use the approve button")
            else:
                self.log.append(("model_failed", type(e).__name__))
            return None
        return parse_model(result.text)

    def _stand_in(self, why):
        if self.gem is not None and hasattr(self.gem, "mark_stand_in"):
            self.gem.mark_stand_in(FEATURE)
        self.log.append(("stand_in", why))

    async def heard(self, transcript):
        """Answer the pending gate from one spoken turn. Returns the gate/answer sent, or None (then the
        transcript is an ordinary command, and the button still answers the gate)."""
        if not self.pending or not (transcript or "").strip():
            return None
        request, deadline = self.pending
        if self.clock() > deadline:
            self.pending = None
            self.log.append(("timed_out", request.get("id")))
            return None
        local = local_decision(transcript)
        if local is None:
            return None               # not an approval word at all: leave it to the command parser
        if self.gem is None or getattr(self.gem, "MODE", "off") == "off":
            self._stand_in("GEMINI_MODE=off: use the approve button")
            return None               # no spoken answers without Gemini: the button answers
        model = self._model(transcript, request)
        if "hold" in (model, local):
            decision = "hold"
        elif model == "approve" and local == "approve":
            decision = "approve"
        else:
            self.log.append(("unclear", request.get("id")))
            return None
        answer = {"id": request["id"], "approved": decision == "approve", "by": "operator"}
        self.pending = None           # consume before the publish: the planner may act re-entrantly
        self.log.append((decision, request["id"]))
        print(f"spoken {decision}: gate {request['id']} ({transcript!r})", file=sys.stderr, flush=True)
        await self.bus.publish("gate/answer", answer)
        return answer


def attach(bus, **kw):
    """Listen for gate/request and gate/answer on the bus; the voice session calls `heard`."""
    global _ACTIVE
    approval = SpokenApproval(bus, **kw)
    bus.subscribe("gate/request", approval.on_request)
    bus.subscribe("gate/answer", approval.on_answer)
    _ACTIVE = approval
    return approval


def active():
    """The SpokenApproval the voice lane started, or None."""
    return _ACTIVE
