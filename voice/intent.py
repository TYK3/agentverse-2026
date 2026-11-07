"""Operator intents: {"goal": ..., "item": ..., "place": ...} and the operator/command text they become.

Two ways in:
- `parse(text)`: a local rule-based parser for typed commands (and the labelled stand-in while
  GEMINI_MODE=off). It resolves a change of mind: "send water to the left room, no, the back room"
  gives the back room.
- `from_model_json(reply)`: the JSON the gemini-3.8-live session returns for a spoken command.

`to_text(intent)` turns either into the one operator/command text the planner reads.
"""

import json
import re

GOALS = ("deliver", "scan", "stop", "return")
# Item ids match responder/action in coord/CONTRACT.md.
ITEMS = ("water", "first_aid_kit", "radio")

_ITEM_WORDS = {
    "first_aid_kit": ["first aid kit", "first-aid kit", "medkit", "med kit", "medical kit", "first aid"],
    "water": ["bottle of water", "water bottle", "water"],
    "radio": ["radio"],
}
_ITEM_SAID = {"water": "water", "first_aid_kit": "the first aid kit", "radio": "the radio"}
_GOAL_WORDS = {
    "deliver": ["send", "bring", "take", "deliver", "drop", "carry", "get"],
    "scan": ["re-look at", "relook at", "look at", "scan", "check", "explore", "inspect", "re-scan", "rescan"],
    "stop": ["stop", "halt", "freeze", "abort", "hold"],
    "return": ["come back", "go back", "head back", "return"],
}
# Words that mean "forget what I just said": "no", "sorry", "I mean", "actually", "make that", ...
_CORRECTION = re.compile(
    r"(?:^|[\s,.;:!?—-])(?:no+|nope|sorry|wait|actually|i mean|scratch that|make that|"
    r"rather|correction|change that)(?=$|[\s,.;:!?—-])[\s,.;:!?—-]*",
    re.IGNORECASE,
)
_PLACE = re.compile(r"\b(?:to|into|in|at|towards|toward)\s+(.+)$", re.IGNORECASE)
_FILLER = re.compile(r"^(?:(?:the|a|an|please|um+|uh+|er+|and|then|so|okay|ok|robot|responder)\b[\s,]*)+",
                     re.IGNORECASE)


def _words(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s'-]", " ", s.lower())).strip()


def _find(s, table):
    """The key whose phrase occurs earliest in s (longest phrase wins a tie), and s with it removed."""
    best = None
    for key, phrases in table.items():
        for p in phrases:
            m = re.search(rf"\b{re.escape(p)}\b", s)
            if m and (best is None or (m.start(), -len(p)) < (best[1].start(), -len(best[2]))):
                best = (key, m, p)
    if best is None:
        return None, s
    key, m, _ = best
    return key, (s[:m.start()] + " " + s[m.end():]).strip()


def _clean_place(s):
    s = _FILLER.sub("", s.strip(" ,.;:!?")).strip(" ,.;:!?")
    s = re.sub(r"\s+please$", "", s)
    return s or None


def _parse_clause(clause):
    """Slots said in one clause: goal, item, place, and any bare noun phrase left over."""
    s = _words(clause)
    goal, s = _find(s, _GOAL_WORDS)
    item, s = _find(s, _ITEM_WORDS)
    place = None
    m = _PLACE.search(s)
    if m:
        place = _clean_place(m.group(1))
        s = s[:m.start()]
    bare = _clean_place(s)
    return {"goal": goal, "item": item, "place": place, "bare": bare}


def parse(text):
    """Return the final intent {"goal", "item", "place"} after every change of mind (missing slots are None)."""
    parts = [p for p in _CORRECTION.split(text) if p and p.strip(" ,.;:!?")]
    intent = {"goal": None, "item": None, "place": None}
    for i, part in enumerate(parts):
        c = _parse_clause(part)
        if i > 0 and c["goal"] is None and c["item"] is None and c["place"] is None and c["bare"]:
            # "..., no, the back room": a bare phrase replaces the place.
            c["place"] = c["bare"]
        if c["goal"] and c["goal"] != intent["goal"]:
            if c["goal"] not in ("deliver",):
                intent["item"] = None
            if c["goal"] in ("stop", "return"):
                intent["place"] = None
            intent["goal"] = c["goal"]
        if c["goal"] == "scan" and c["place"] is None and c["bare"]:
            c["place"] = c["bare"]  # "check the left room"
        for slot in ("item", "place"):
            if c[slot]:
                intent[slot] = c[slot]
    if intent["goal"] is None and intent["item"]:
        intent["goal"] = "deliver"  # "water to the back room"
    return intent


def from_model_json(reply):
    """Parse the live model's reply (JSON, maybe in a ``` fence) into an intent. Raises ValueError."""
    m = re.search(r"\{.*\}", reply or "", re.DOTALL)
    if not m:
        raise ValueError(f"no JSON object in model reply: {reply!r}")
    raw = json.loads(m.group(0))
    goal = raw.get("goal")
    item = raw.get("item")
    item = item.replace(" ", "_") if isinstance(item, str) else None
    if goal is not None and goal not in GOALS:
        raise ValueError(f"unknown goal {goal!r}")
    if item is not None and item not in ITEMS:
        raise ValueError(f"unknown item {item!r}")
    place = raw.get("place")
    return {"goal": goal, "item": item, "place": _clean_place(place.lower()) if isinstance(place, str) else None}


def to_text(intent):
    """The operator/command text for an intent, or None if the intent is incomplete."""
    goal, item, place = intent.get("goal"), intent.get("item"), intent.get("place")
    if goal == "deliver" and item and place:
        return f"send {_ITEM_SAID[item]} to the {place}"
    if goal == "scan" and place:
        return f"scan the {place}"
    if goal == "stop":
        return "stop"
    if goal == "return":
        return "return to base"
    return None
