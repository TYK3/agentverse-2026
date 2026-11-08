"""G3: bounded live contact with one casualty. Every line the robot says answers what it just heard.

Not a voice-over: the robot does not read a script at the casualty. After each `casualty/reply` it
works out what the casualty told it (facts) and picks the next move from what is still unknown or
what the answer makes urgent: "it's bleeding" brings the bleeding self-care line next, "my leg, I
think it's broken" skips "where does it hurt" and asks about moving, then says "keep your leg still".

Bounded, so it is safe to run live:
- the robot only ever says lines from MOVES (fixed, short, plain words). Self-care lines come from
  voice/firstaid.json steps (cited) and are guidance, never a diagnosis;
- Gemini (through coord/gem.py, one receipt per call) may only pick the next move id from the allowed
  list, update known fact keys and add a short acknowledgement (ACK_WORDS words at most, with no
  medical advice words); anything else in its answer is dropped and the local reader is used;
- at most MAX_TURNS robot lines and MAX_S seconds per casualty; REPLY_WAIT_S without an answer
  repeats the question once, and MAX_SILENT unanswered lines end the contact as unresponsive;
- an aftershock (`world/change`) stops it at once with the protect-your-head line;
- in range only (CONTACT-HAS-RANGE): a contact starts only while the Scout is within HEAR_M of the
  casualty's `map/casualties` pos and on its floor, as a casualty hears a call only that close
  (sim/world.py HEAR_CALL_M). While the Scout is out of range an unanswered line does not count as
  silence, so a casualty nobody could hear is never reported "unresponsive". With no Scout pose or no
  casualty pos yet, range is not checked.

In:  map/casualties (starts contact with the most confident casualty in range), casualty/reply,
     world/change, sensors/scout (the Scout's pose, for range).
Out: say (to the casualty), casualty/contact (status, facts, injuries in their words, receipts) and
     log/decision (heard -> understood -> said, model "local-contact" or the Gemini model id).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from voice import firstaid

MAX_TURNS = 8          # robot lines per casualty
MAX_S = 120.0          # seconds per casualty
REPLY_WAIT_S = 10.0    # wait this long for an answer before repeating the question
MAX_SILENT = 2         # unanswered lines in a row -> unresponsive
ACK_WORDS = 12         # Gemini's acknowledgement before the fixed line, at most this many words
GEM_TIMEOUT_S = 4.0
START_CONFIDENCE = 0.5
HEAR_M = 6.0           # the Scout must be this close (plan view) to talk: sim/world.py HEAR_CALL_M
SAME_FLOOR_M = 0.3     # and this close in height (floors are 0.6 m apart)
MODEL = "local-contact"

FACTS = ("responsive", "hurt", "bleeding", "breathing_hard", "can_move", "cold", "can_walk")
# move id -> (line, intent, fact it asks about or None, firstaid.json action it cites or None)
MOVES: dict[str, tuple[str, str, str | None, str | None]] = {
    "hear": ("Hello, I am a rescue robot. Can you hear me? If you can, say yes.", "reassure", "responsive", None),
    "where": ("Are you hurt? Tell me where it hurts.", "first_aid", "hurt", None),
    "bleeding": ("Are you bleeding anywhere?", "first_aid", "bleeding", None),
    "breathing": ("Is it hard to breathe?", "first_aid", "breathing_hard", None),
    "move": ("Can you move your arms and legs?", "first_aid", "can_move", None),
    "cold": ("Are you cold or wet?", "first_aid", "cold", None),
    "walk": ("Do you think you could stand up and walk?", "first_aid", "can_walk", None),
    # Self-care lines are the cited steps' casualty_line in voice/firstaid.json (ref FIRSTAID-SOURCES).
    "care_bleeding": (firstaid.casualty_line("control_bleeding"), "first_aid", None, "control_bleeding"),
    "care_spine": (firstaid.casualty_line("protect_spine"), "first_aid", None, "protect_spine"),
    "care_still": (firstaid.casualty_line("keep_limb_still"), "first_aid", None, "keep_limb_still"),
    "care_breathing": (firstaid.casualty_line("protect_airway_from_dust"), "first_aid", None,
                       "protect_airway_from_dust"),
    "care_warm": (firstaid.casualty_line("keep_warm"), "first_aid", None, "keep_warm"),
    "close": ("Thank you. You did well. Stay where you are. Rescuers know where you are and are coming.",
              "reassure", None, "reassure_and_monitor"),
}
QUESTIONS = ("hear", "where", "bleeding", "breathing", "move", "cold", "walk")
AFTERSHOCK = "Stop. Stay where you are. Cover your head with your arms. I am still here."
BANNED = ("diagnos", "you have a", "medicine", "medication", "pill", "tablet", "inject", "tourniquet", "surgery",
          "fracture", "concussion", "you will be fine", "promise")

SPINE = ("head", "neck", "back", "spine")   # hurt here -> keep head and neck still (protect_spine)
PARTS = ("head", "neck", "back", "spine", "chest", "stomach", "belly", "arm", "hand", "leg", "knee", "foot",
         "ankle", "hip", "shoulder", "face", "eye", "ribs", "wrist")
_YES = re.compile(r"\b(yes|yeah|yep|i can|i am|i'm so|it is|it's (bleeding|hard))\b")
_NO = re.compile(r"\b(no|nope|not|can't|cannot|don't|isn't)\b")


@dataclass
class Session:
    cid: str
    started: float
    facts: dict[str, Any] = field(default_factory=lambda: {k: None for k in FACTS})
    injuries: list[str] = field(default_factory=list)
    asked: list[str] = field(default_factory=list)       # move ids said, in order
    waiting: str | None = None                           # move id whose answer we wait for
    said_at: float = 0.0
    repeated: bool = False
    silent: int = 0
    revived: int = 0                                     # times picked up again after a late answer
    status: str = "talking"
    receipts: list[str] = field(default_factory=list)
    transcript: list[tuple[str, str]] = field(default_factory=list)   # (who, text)


# ---- reading one answer (local, offline) ------------------------------------------------------

def read_answer(move: str | None, text: str) -> dict[str, Any]:
    """Facts one English reply states. Keys from FACTS only; values true/false or a list of parts.

    It reads the reply itself, not only the question: "my leg, I think it's broken, and it's bleeding"
    answers more than the question asked."""
    t = " " + " ".join(text.lower().replace(",", " ").replace(".", " ").replace("!", " ").split()) + " "
    out: dict[str, Any] = {}
    if not text.strip():
        return out
    out["responsive"] = True
    yes, no = bool(_YES.search(t)), bool(_NO.search(t))
    parts = _hurt_parts(move, text)
    if parts:
        out["hurt"] = parts
    if "bleed" in t or "blood" in t:
        out["bleeding"] = not re.search(r"\b(not|don't|no)\b[^.]*\bbleed", t)
    if "breath" in t or "dust" in t:
        out["breathing_hard"] = "hard" in t or "can't breathe" in t or ("dust" in t and "can breathe" not in t)
    if "cold" in t or "freez" in t:
        out["cold"] = not re.search(r"\bnot\b[^.]*\bcold", t)
    if " stand " in t or " walk " in t:
        out["can_walk"] = yes and not ("can't" in t or "cannot" in t)
    asks = MOVES[move][2] if move in MOVES else None
    if asks and asks not in out:
        if asks == "hurt":
            if no and not parts:
                out["hurt"] = []
        elif asks == "can_move":
            out["can_move"] = yes and not no
        elif yes != no:
            out[asks] = yes
    return out


_PAINFUL = re.compile(r"\b(hurt|hurts|pain|broken|bleed|bleeding|blood|cut|stuck|trapped|can't|cannot|not)\b")


def _hurt_parts(move: str | None, text: str) -> list[str]:
    """Body parts the reply says are hurt. A part counts when its clause is about pain or is negative
    ("my arms, yes. Not my left leg" -> leg), or when the question was where it hurts."""
    out = []
    for clause in re.split(r"[.,;!?]| and | but ", text.lower()):
        named = [p for p in PARTS if re.search(rf"\b{p}s?\b", clause)]
        if named and (move == "where" or _PAINFUL.search(clause)):
            out += [p for p in named if p not in out]
    return out


def injury_words(text: str) -> str | None:
    """The casualty's own words about an injury, if the reply has any (kept as said, never diagnosed)."""
    t = text.lower()
    if any(w in t for w in ("hurt", "broken", "bleed", "blood", "cut", "pain", "breathe", "cold")) and not t.startswith("no,"):
        return text.strip()[:120]
    return None


def next_move(s: Session) -> str:
    """Local policy: the most urgent self-care line the facts call for, else the next useful question."""
    f, asked = s.facts, set(s.asked)
    if f["bleeding"] and "care_bleeding" not in asked:
        return "care_bleeding"
    if f["breathing_hard"] and "care_breathing" not in asked:
        return "care_breathing"
    hurt = f["hurt"] or []
    if any(p in hurt for p in SPINE) and "care_spine" not in asked:
        return "care_spine"   # head, neck or back: keep still at once, before asking them to move anything
    if hurt and "move" not in asked and f["can_move"] is None and "care_spine" not in asked:
        return "move"
    if hurt and f["can_move"] is not None and not asked & {"care_still", "care_spine"} and (
            f["can_move"] is False or "leg" in hurt):
        return "care_still"
    if f["cold"] and "care_warm" not in asked:
        return "care_warm"
    for q in QUESTIONS:
        fact = MOVES[q][2]
        if q in asked or f[fact] is not None:
            continue
        if q == "move" and "care_spine" in asked:
            continue          # never ask someone told to keep their head and neck still to move
        if q == "walk" and (f["can_move"] is False or asked & {"care_still", "care_spine"}):
            continue          # do not suggest walking with a part that must stay still
        return q
    return "close"


def _allowed(s: Session) -> list[str]:
    done = set(s.asked)
    return [m for m in MOVES if m not in done or m == "close"]


def check_gemini(raw: str, s: Session) -> dict[str, Any] | None:
    """Gemini's {"facts", "next", "ack"} if it stays inside the bounds, else None."""
    try:
        got = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
    except (ValueError, AttributeError):
        return None
    if not isinstance(got, dict) or got.get("next") not in _allowed(s):
        return None
    facts = {}
    for k, v in (got.get("facts") or {}).items():
        if k in FACTS and (v is None or isinstance(v, bool) or (k == "hurt" and isinstance(v, list)
                                                                 and all(isinstance(p, str) for p in v))):
            facts[k] = v
    ack = str(got.get("ack") or "").strip()
    if len(ack.split()) > ACK_WORDS or any(b in ack.lower() for b in BANNED) or "?" in ack:
        ack = ""
    return {"facts": facts, "next": got["next"], "ack": ack}


def gemini_prompt(s: Session, reply: str) -> str:
    lines = "\n".join(f"{who}: {text}" for who, text in s.transcript[-8:])
    moves = "\n".join(f"- {m}: {MOVES[m][0]}" for m in _allowed(s))
    return (
        "You help a rescue robot talk with a trapped earthquake casualty. You never diagnose and never give "
        "medical advice of your own.\n"
        f"Conversation so far:\n{lines}\nCasualty just said: {reply!r}\n"
        f"Known facts: {json.dumps(s.facts)}\n"
        f"Choose the next robot move from this list only (the robot says the fixed line):\n{moves}\n"
        "Prefer a self-care move the answer makes urgent, else the next unknown question; never suggest "
        "walking if a limb, the neck or the back hurts. Reply with JSON only: "
        '{"facts": {<only keys from ' + ", ".join(FACTS) + '>}, "next": "<move id>", '
        f'"ack": "<at most {ACK_WORDS} calm words acknowledging what they said, no advice, no question>"}}'
    )


def _source(action: str) -> str:
    step = firstaid.get_step(action)
    return step["source"] if step else "?"


def _gem():
    try:
        from coord import gem
        return gem
    except ImportError:
        return None


# ---- the contact service ----------------------------------------------------------------------

class Contact:
    """One casualty at a time. Pure core: methods return the messages to publish as (topic, data)."""

    def __init__(self, gem=None, clock=time.monotonic):
        self.gem = gem if gem is not None else _gem()
        self.clock = clock
        self.sessions: dict[str, Session] = {}
        self.active: str | None = None
        self.queue: list[str] = []
        self.scout: list[float] | None = None          # the Scout's sensor position, from sensors/scout
        self.where: dict[str, list[float]] = {}        # casualty id -> pos from map/casualties

    # -- in --
    def on_casualties(self, casualties: list[dict[str, Any]], now: float | None = None) -> list[tuple[str, Any]]:
        now = self.clock() if now is None else now
        for c in sorted(casualties, key=lambda c: -c.get("confidence", 0)):
            if c.get("pos"):
                self.where[c["id"]] = list(c["pos"])
            if c.get("confidence", 0) >= START_CONFIDENCE and c["id"] not in self.sessions and c["id"] not in self.queue:
                self.queue.append(c["id"])
        return self._start_next(now)

    def on_scout(self, pos, now: float | None = None) -> list[tuple[str, Any]]:
        """The Scout's position (sensors/scout pose.pos): a queued casualty may now be in range."""
        now = self.clock() if now is None else now
        self.scout = list(pos)
        return self._start_next(now)

    def in_range(self, cid: str) -> bool:
        """Whether casualty `cid` can hear the Scout: within HEAR_M and on its floor (True if unknown)."""
        c = self.where.get(cid)
        if self.scout is None or c is None:
            return True
        far = ((c[0] - self.scout[0]) ** 2 + (c[1] - self.scout[1]) ** 2) ** 0.5 > HEAR_M
        return not far and (len(c) < 3 or len(self.scout) < 3 or abs(c[2] - self.scout[2]) <= SAME_FLOOR_M)

    def on_world_change(self, data: dict[str, Any], now: float | None = None) -> list[tuple[str, Any]]:
        now = self.clock() if now is None else now
        s = self.sessions.get(self.active) if self.active else None
        if not s:
            return []
        s.status, self.active = "stopped", None
        s.transcript.append(("robot", AFTERSHOCK))
        return [("say", {"to": "casualty", "intent": "reassure", "text": AFTERSHOCK, "lang": "auto"}),
                self._log(s, now, f"{data.get('kind', 'world change')}", "stopped",
                          "aftershock: stop talking, tell them to protect their head"),
                self._contact(s, now)]

    def hear(self, data: dict[str, Any], interpret=None, now: float | None = None) -> list[tuple[str, Any]]:
        """A casualty/reply. `interpret(session, text)` -> checked Gemini answer or None (default: none)."""
        now = self.clock() if now is None else now
        s = self.sessions.get(data.get("id"))
        if not self.accepts(data.get("id")):
            return []
        revived = []
        if s.status == "unresponsive":
            # A late answer: the casualty was slower than REPLY_WAIT_S (or the sim ran behind the wall
            # clock), so "unresponsive" was wrong. Pick the contact up again; MAX_TURNS still bounds it
            # (ref LATE-REPLY).
            s.status, s.revived, s.silent, s.started, s.said_at = "talking", s.revived + 1, 0, now, now
            s.waiting = next((m for m in reversed(s.asked) if MOVES[m][2]), None)   # what they answer
            self.active = s.cid
            if s.cid in self.queue:
                self.queue.remove(s.cid)
            revived = [self._log(s, now, f"heard {s.cid} after unresponsive", "resumed",
                                 "late answer: responsive after all, contact picked up again")]
        text = data.get("text", "")
        s.transcript.append(("casualty", text))
        s.silent, s.repeated = 0, False
        local = read_answer(s.waiting, text)
        got, model, receipt = (interpret(s, text) if interpret else (None, MODEL, None))
        facts = dict(local)
        if got:
            facts.update({k: v for k, v in got["facts"].items() if v is not None})
        for k, v in facts.items():
            if k == "hurt" and isinstance(v, list):
                s.facts["hurt"] = sorted(set((s.facts["hurt"] or []) + v)) if v else (s.facts["hurt"] or [])
            else:
                s.facts[k] = v
        words = injury_words(text)
        if words and words not in s.injuries:
            s.injuries.append(words)
        if receipt:
            s.receipts.append(receipt)
        move = got["next"] if got else next_move(s)
        ack = got["ack"] if got else ""
        understood = ", ".join(f"{k}={v}" for k, v in facts.items()) or "nothing new"
        return [*revived, self._log(s, now, f"heard {s.cid}: {text!r}", "understood", understood, model=model),
                *self._say(s, move, now, ack=ack, model=model)]

    def accepts(self, cid) -> bool:
        """Whether a casualty/reply from `cid` is heard: the active contact, or one ended as unresponsive
        with robot lines left (MAX_TURNS) while no other contact is running."""
        s = self.sessions.get(cid)
        if s is None:
            return False
        if s.status == "talking":
            return cid == self.active
        return s.status == "unresponsive" and len(s.asked) < MAX_TURNS and self.active in (None, cid)

    def tick(self, now: float | None = None) -> list[tuple[str, Any]]:
        now = self.clock() if now is None else now
        s = self.sessions.get(self.active) if self.active else None
        if not s or s.status != "talking":
            return self._start_next(now)
        if now - s.started >= MAX_S:
            return self._end(s, now, "done", f"time cap {MAX_S:.0f} s reached")
        if s.waiting and now - s.said_at >= REPLY_WAIT_S:
            if not self.in_range(s.cid):   # nobody could hear it: not silence, wait for the Scout
                s.said_at = now
                return []
            s.silent += 1
            if s.silent >= MAX_SILENT:
                return self._end(s, now, "unresponsive", f"no answer to {s.silent} lines")
            s.repeated = True
            return self._say(s, s.waiting, now, repeat=True)
        return []

    # -- helpers --
    def _start_next(self, now):
        if self.active:
            return []
        cid = next((q for q in self.queue if self.in_range(q)), None)
        if cid is None:
            return []
        self.queue.remove(cid)
        s = self.sessions[cid] = Session(cid, now)
        self.active = cid
        return self._say(s, "hear", now)

    def _say(self, s: Session, move: str, now: float, ack: str = "", model: str = MODEL, repeat=False):
        if move == "close" or (len(s.asked) >= MAX_TURNS and not repeat):
            return self._end(s, now, "done", "all useful questions answered" if move == "close"
                             else f"turn cap {MAX_TURNS} reached")
        line, intent, asks, cites = MOVES[move]
        text = (ack.rstrip(".") + ". " if ack else "") + line
        if not repeat:
            s.asked.append(move)
        s.waiting = move if asks else None
        s.said_at = now
        s.transcript.append(("robot", text))
        out = [("say", {"to": "casualty", "intent": intent, "text": text, "lang": "auto"}),
               self._log(s, now, f"contact {s.cid} turn {len(s.asked)}/{MAX_TURNS}", "repeat" if repeat else "say",
                         f"{move}" + (f" (cites {cites}: {_source(cites)})" if cites else "") + f": {text}",
                         model=model),
               self._contact(s, now)]
        if not asks and not repeat:   # a self-care line expects no answer: the next move follows at once
            out += self._say(s, next_move(s), now)
        return out

    def _end(self, s: Session, now: float, status: str, why: str):
        s.status, s.waiting = status, None
        out = []
        if status == "done":
            line = MOVES["close"][0]
            s.transcript.append(("robot", line))
            out.append(("say", {"to": "casualty", "intent": "reassure", "text": line, "lang": "auto"}))
        out += [self._log(s, now, f"contact {s.cid}", status, why), self._contact(s, now)]
        self.active = None
        return out + self._start_next(now)

    def _contact(self, s: Session, now: float):
        facts = {k: v for k, v in s.facts.items()}
        return ("casualty/contact", {"id": s.cid, "t": round(max(0.0, now), 2), "status": s.status,
                                     "turns": len(s.asked), "max_turns": MAX_TURNS, "facts": facts,
                                     "injuries": list(s.injuries), "receipts": list(s.receipts)})

    def _log(self, s, now, perception, outcome, reason, model=MODEL):
        return ("log/decision", {"t": round(max(0.0, now), 2), "perception": perception, "model": model,
                                 "physics": "", "outcome": outcome, "reason": reason[:300]})

    def summary(self, cid: str) -> dict[str, Any] | None:
        s = self.sessions.get(cid)
        return None if s is None else self._contact(s, self.clock())[1]

    # -- Gemini, bounded --
    def interpret_with_gemini(self, s: Session, text: str):
        """(checked answer or None, model name, receipt id or None). Never raises."""
        gem = self.gem
        if not gem:                       # None or False: no Gemini in this process
            return None, MODEL, None
        prompt = gemini_prompt(s, text)
        try:
            if hasattr(gem, "ask_with_receipt"):
                res = gem.ask_with_receipt("fast_subagent", prompt, thinking="low", feature="casualty_contact")
                raw, receipt = res.text, res.receipt.get("id")
            else:
                raw, receipt = gem.ask("fast_subagent", prompt, thinking="low", feature="casualty_contact"), None
        except Exception as exc:  # noqa: BLE001 - off, cap, network, SDK: the local reader carries on
            if type(exc).__name__ == "GeminiOff" and hasattr(gem, "mark_stand_in"):
                gem.mark_stand_in("casualty_contact")
            return None, MODEL, None
        got = check_gemini(raw, s)
        model = getattr(gem, "MODEL_IDS", {}).get("fast_subagent", "gemini")
        return (got, model, receipt) if got else (None, MODEL + " (gemini answer out of bounds)", receipt)


def start(bus, *, clock=None, gem=None):
    """Wire contact to the hub bus and return it. Timeouts (no answer, time cap) run on loop timers set
    after each line, so there is no background task for the hub to cancel."""
    loop = asyncio.get_running_loop()
    c = Contact(gem=gem, clock=clock or loop.time)
    c.timers = set()

    def check_later():
        for delay in (REPLY_WAIT_S + 0.05, MAX_S + 0.05):
            handle = loop.call_later(delay, lambda: loop.create_task(emit(c.tick())))
            c.timers.add(handle)

    async def emit(msgs):
        for topic, data in msgs:
            await bus.publish(topic, data)
        if any(topic == "say" for topic, _ in msgs):
            check_later()

    async def on_reply(data):
        s = c.sessions.get(data.get("id"))
        if not c.accepts(data.get("id")):
            return
        got = (None, MODEL, None)
        if c.gem:
            try:
                got = await asyncio.wait_for(asyncio.to_thread(c.interpret_with_gemini, s, data.get("text", "")),
                                             GEM_TIMEOUT_S)
            except TimeoutError:
                got = (None, MODEL + " (gemini timed out)", None)
        await emit(c.hear(data, interpret=lambda _s, _t: got))

    async def on_cas(data):
        await emit(c.on_casualties(data))

    async def on_change(data):
        await emit(c.on_world_change(data))

    async def on_scout(data):
        pos = (data.get("pose") or {}).get("pos")
        if pos:
            await emit(c.on_scout(pos))

    bus.subscribe("map/casualties", on_cas)
    bus.subscribe("casualty/reply", on_reply)
    bus.subscribe("world/change", on_change)
    bus.subscribe("sensors/scout", on_scout)
    return c
