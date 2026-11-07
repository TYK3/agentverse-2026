"""Guide voice (Y5): a calm voice inside the building for each casualty.

For every casualty in `map/casualties` the guide:
1. reassures them ("You are not alone. A rescue robot is with you. Help is coming."),
2. asks short injury questions one at a time and records the answers,
3. if they can walk safely, reads out the way out, which is the Responder's own verified route
   walked backwards (the only path the physics check has cleared); otherwise it asks them to stay
   still and keeps reassuring them.

An aftershock (`world/change`) stops anyone walking ("Stop. Stay where you are. Protect your head.")
and drops the old exit route until a new one is verified.

The Guide class is pure: every method returns the `say`-shaped lines to speak, so it can be tested
without a bus or audio. `voice.start(bus)` wires it to the hub and speaks the lines through
`voice.speak` (translated to the casualty's language, calm TTS style).

Casualty answers come in through `Guide.hear(casualty_id, text)` (already in English, or translated
with `translate.translate_casualty_reply`). Answers are guidance for humans, never a diagnosis.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

REPEAT_AFTER_S = 12.0  # ask again if there is no answer
GIVE_UP_AFTER = 2  # unanswered asks before the guide moves on
REASSURE_EVERY_S = 30.0  # while waiting for rescue, a calm line this often
ROUTE_END_MATCH_M = 1.0  # a verified route ending this close to a casualty is their way out
TURN_DEG = 35.0  # heading change that counts as a turn
SIMPLIFY_M = 0.12  # path wiggles smaller than this are not read out

# (id, question). Order matters: the cheapest, most useful answers first.
QUESTIONS: list[tuple[str, str]] = [
    ("hear", "Can you hear me? If you can, say yes."),
    ("hurt", "Are you hurt? Tell me where it hurts."),
    ("breathing", "Is it hard to breathe?"),
    ("bleeding", "Are you bleeding?"),
    ("move", "Can you move your arms and legs?"),
    ("walk", "Do you think you can stand up and walk if I show you the way?"),
]
QUESTION_TEXT = dict(QUESTIONS)

YES = {"yes", "yeah", "yep", "i can", "i do", "i am", "i'm", "ok", "okay", "sure", "a little", "it is",
       "hurt", "hurts", "pain", "bleeding", "blood"}
NO = {"no", "nope", "not", "can't", "cannot", "don't", "isn't", "i'm not", "never"}
UNSURE = {"don't know", "not sure", "maybe", "unsure", "i think so", "dont know"}
BODY_PARTS = ["head", "neck", "back", "spine", "chest", "stomach", "belly", "arm", "hand", "leg",
              "knee", "foot", "ankle", "hip", "shoulder", "face", "eye", "ribs"]
# Walking is not suggested if one of these is hurt: possible spinal or head injury.
DO_NOT_MOVE_PARTS = {"head", "neck", "back", "spine"}

GREETING = ("Hello. I am a rescue robot. You are not alone. "
            "Rescuers know where you are and help is coming.")
STAY_STILL = ("Please stay where you are and keep still. "
              "The rescue team is coming to you. I will stay with you.")
FINDING_WAY = "I am checking a safe way out. Please stay where you are for now."
AFTERSHOCK = "Stop. Stay where you are. Cover your head with your arms. I am still here."
CALM_LINES = [
    "You are doing well. Breathe slowly. Help is on the way.",
    "I am still here with you. The rescuers are coming.",
    "Try to stay calm and keep warm. You are not alone.",
]
ARRIVED = "That is the way out. Keep walking slowly, away from the building, and wait for the rescuers."


def classify(question: str, text: str) -> dict[str, Any]:
    """Turn one English answer into {"answer": "yes"|"no"|"unsure"|"none", ...}.

    Local keyword reading, so it works offline. "hurt" also lists body parts mentioned.
    """
    t = " " + " ".join(text.lower().replace(",", " ").replace(".", " ").split()) + " "
    out: dict[str, Any] = {"question": question, "text": text.strip()}
    parts = [p for p in BODY_PARTS if f" {p} " in t or f" {p}s " in t or f" my {p}" in t]
    if not text.strip() or text.strip().startswith("[translation unavailable"):
        out["answer"] = "none"
    elif any(f" {w} " in t for w in UNSURE):
        out["answer"] = "unsure"
    elif any(f" {w} " in t for w in NO):
        out["answer"] = "no"
    elif any(f" {w} " in t for w in YES) or (question == "hurt" and parts):
        out["answer"] = "yes"
    else:
        out["answer"] = "unsure"
    if question == "hurt":
        out["parts"] = parts
    return out


def _simplify(pts: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker: keep only the corners of a grid path."""
    if len(pts) < 3:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    seg = math.hypot(x1 - x0, y1 - y0) or 1e-9
    far, idx = 0.0, 0
    for i, (x, y) in enumerate(pts[1:-1], 1):
        d = abs((x1 - x0) * (y0 - y) - (x0 - x) * (y1 - y0)) / seg
        if d > far:
            far, idx = d, i
    if far <= eps:
        return [pts[0], pts[-1]]
    return _simplify(pts[: idx + 1], eps)[:-1] + _simplify(pts[idx:], eps)


def _metres(d: float) -> str:
    if d < 0.75:
        return "a step or two"
    m = round(d * 2) / 2
    if m == 1:
        return "about one metre"
    return f"about {m:g} metres"


def exit_directions(cells: list[list[int]], res: float) -> list[str]:
    """Spoken steps for walking a cell path from its first cell to its last.

    The first leg is described as "towards the robot's light", since the casualty's own facing is
    unknown; later legs are left/right turns relative to the leg before.
    """
    pts = [((c[0] + 0.5) * res, (c[1] + 0.5) * res) for c in cells]
    pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
    pts = _simplify(pts, SIMPLIFY_M)
    if len(pts) < 2:
        return [ARRIVED]
    steps: list[str] = []
    prev = None
    for (ax, ay), (bx, by) in itertools.pairwise(pts):
        heading = math.atan2(by - ay, bx - ax)
        dist = _metres(math.hypot(bx - ax, by - ay))
        if prev is None:
            steps.append(f"Walk slowly towards the robot's light, {dist}.")
        else:
            turn = math.degrees((heading - prev + math.pi) % (2 * math.pi) - math.pi)
            if abs(turn) < TURN_DEG:
                steps.append(f"Keep going straight, {dist}.")
            elif abs(turn) > 150:
                steps.append(f"Turn around and walk back, {dist}.")
            else:
                side = "left" if turn > 0 else "right"  # z up: counter-clockwise is a left turn
                steps.append(f"Turn {side}, then walk {dist}.")
        prev = heading
    steps.append(ARRIVED)
    return steps


@dataclass
class Session:
    """The guide's conversation with one casualty."""

    cid: str
    pos: list[float]
    answers: dict[str, dict[str, Any]] = field(default_factory=dict)
    asking: str | None = None
    asked_at: float = 0.0
    tries: int = 0
    last_spoke: float = 0.0
    calm_i: int = 0
    phase: str = "questions"  # questions | guiding | waiting
    exit_route: str | None = None

    def can_walk(self) -> bool:
        a = self.answers
        if a.get("walk", {}).get("answer") != "yes":
            return False
        if a.get("move", {}).get("answer") == "no" or a.get("breathing", {}).get("answer") == "yes":
            return False
        return not DO_NOT_MOVE_PARTS & set(a.get("hurt", {}).get("parts", []))


def _say(text: str, intent: str) -> dict[str, Any]:
    return {"to": "casualty", "intent": intent, "text": text, "lang": "auto"}


class Guide:
    """Per-casualty guide voice. Every method returns the list of `say` lines to speak."""

    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self.res = 0.05
        self.proposed: dict[str, list[list[int]]] = {}
        self.verified: dict[str, list[list[int]]] = {}  # route id -> cells, ok routes only
        self.answer_log: list[dict[str, Any]] = []

    # ---- bus inputs -------------------------------------------------------------------------
    def on_cells(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        res = data.get("res")
        if isinstance(res, (int, float)) and res > 0:
            self.res = float(res)
        return []

    def on_casualties(self, casualties: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for c in casualties:
            s = self.sessions.get(c["id"])
            if s is None:
                s = self.sessions[c["id"]] = Session(c["id"], list(c["pos"]))
                out.append(_say(GREETING, "reassure"))
                out += self._next_question(s, now)
            else:
                s.pos = list(c["pos"])
        return out

    def on_route_proposed(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        self.proposed[data["id"]] = [list(c) for c in data["cells"]]
        return []

    def on_route_verified(self, data: dict[str, Any], now: float) -> list[dict[str, Any]]:
        cells = self.proposed.get(data["id"])
        if not data.get("ok") or not cells:
            self.verified.pop(data["id"], None)
            return []
        self.verified[data["id"]] = cells
        out: list[dict[str, Any]] = []
        for s in self.sessions.values():
            if s.phase == "waiting" and s.can_walk() and self._exit_for(s):
                out += self._start_guiding(s, now)
        return out

    def on_world_change(self, data: dict[str, Any], now: float) -> list[dict[str, Any]]:
        """Old routes are no longer trusted. Anyone being guided stops and waits."""
        self.verified.clear()
        out: list[dict[str, Any]] = []
        for s in self.sessions.values():
            if s.phase == "guiding":
                s.phase, s.exit_route = "waiting", None
                out.append(_say(AFTERSHOCK, "reassure"))
                s.last_spoke = now
        return out

    def hear(self, cid: str, text: str, now: float) -> list[dict[str, Any]]:
        """A casualty answered (English text). Record it and say what comes next."""
        s = self.sessions.get(cid)
        if s is None:
            return []
        if s.phase == "guiding":  # any reply while walking: read the way out again
            return self._directions(s, now)
        if s.asking is None:
            return []
        ans = classify(s.asking, text)
        ans["casualty"] = cid
        s.answers[s.asking] = ans
        self.answer_log.append(ans)
        s.asking, s.tries = None, 0
        return self._next_question(s, now)

    def tick(self, now: float) -> list[dict[str, Any]]:
        """Called about once a second: repeat unanswered questions, keep reassuring."""
        out: list[dict[str, Any]] = []
        for s in self.sessions.values():
            if s.asking and now - s.asked_at >= REPEAT_AFTER_S:
                if s.tries < GIVE_UP_AFTER:
                    s.tries += 1
                    s.asked_at = s.last_spoke = now
                    out.append(_say(QUESTION_TEXT[s.asking], "reassure"))
                else:
                    ans = {"casualty": s.cid, "question": s.asking, "text": "", "answer": "none"}
                    s.answers[s.asking] = ans
                    self.answer_log.append(ans)
                    s.asking, s.tries = None, 0
                    out += self._next_question(s, now)
            elif s.phase == "waiting" and now - s.last_spoke >= REASSURE_EVERY_S:
                out.append(_say(CALM_LINES[s.calm_i % len(CALM_LINES)], "reassure"))
                s.calm_i += 1
                s.last_spoke = now
        return out

    # ---- outputs for other lanes (Y3 triage, Y6 report) ------------------------------------
    def summary(self, cid: str) -> dict[str, Any]:
        s = self.sessions[cid]
        return {"casualty": cid, "answers": {q: a["answer"] for q, a in s.answers.items()},
                "hurt_parts": s.answers.get("hurt", {}).get("parts", []),
                "can_walk": s.can_walk(), "phase": s.phase,
                "note": "self-reported answers, guidance only, not a diagnosis"}

    # ---- internals --------------------------------------------------------------------------
    def _next_question(self, s: Session, now: float) -> list[dict[str, Any]]:
        if s.answers.get("hear", {}).get("answer") in ("none", "no"):
            # No response: stop questioning, keep a calm presence for whoever can hear.
            return self._wait(s, now, STAY_STILL)
        for qid, text in QUESTIONS:
            if qid not in s.answers:
                s.asking, s.asked_at, s.tries, s.last_spoke = qid, now, 0, now
                return [_say(text, "reassure")]
        if s.can_walk():
            if self._exit_for(s):
                return self._start_guiding(s, now)
            return self._wait(s, now, FINDING_WAY)
        return self._wait(s, now, STAY_STILL)

    def _wait(self, s: Session, now: float, line: str) -> list[dict[str, Any]]:
        s.phase, s.asking, s.last_spoke = "waiting", None, now
        return [_say(line, "reassure")]

    def _exit_for(self, s: Session) -> str | None:
        """The newest verified route that ends at this casualty."""
        for rid in reversed(list(self.verified)):
            end = self.verified[rid][-1]
            ex, ey = (end[0] + 0.5) * self.res, (end[1] + 0.5) * self.res
            if math.hypot(ex - s.pos[0], ey - s.pos[1]) <= ROUTE_END_MATCH_M:
                return rid
        return None

    def _start_guiding(self, s: Session, now: float) -> list[dict[str, Any]]:
        s.phase, s.exit_route = "guiding", self._exit_for(s)
        return self._directions(s, now)

    def _directions(self, s: Session, now: float) -> list[dict[str, Any]]:
        cells = self.verified.get(s.exit_route or "")
        if not cells:
            return self._wait(s, now, FINDING_WAY)
        s.last_spoke = now
        intro = "I found a safe way out. Stand up slowly. Follow these steps."
        steps = exit_directions(list(reversed(cells)), self.res)  # the Responder came in this way
        return [_say(line, "guide_exit") for line in [intro, *steps]]
