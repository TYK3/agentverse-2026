"""G3: what a simulated casualty says back when the robot speaks to them.

Each casualty has a fixed persona (their injuries and state). `answer(persona, line)` returns the
reply to one robot line, picked by what the line asks, so a robot that ignores the answers gets the
same facts over and over, and one that listens can move on. Statements (reassurance, first aid)
get a short acknowledgement. A silent casualty (scene voice 0) never speaks; they only knock (L2).

This is sim truth: voice/contact.py only ever sees the reply text on `casualty/reply`, as a robot
would hear it through its microphone.
"""

from __future__ import annotations

PERSONAS = {
    # c1 (backup scene, room 3): leg trapped and probably broken, cold, not bleeding, breathing fine.
    "c1": {"hurt": "my left leg", "broken": True, "bleeding": False, "breathing_hard": False, "cold": True,
           "arms_ok": True, "walk": False},
    # c2 (tower): a cut forearm that is bleeding, can walk.
    "c2": {"hurt": "my right arm, there's a cut", "broken": False, "bleeding": True, "breathing_hard": False,
           "cold": False, "arms_ok": False, "walk": True},
    # c3 (tower): dust, hard to breathe, chest hurts.
    "c3": {"hurt": "my chest", "broken": False, "bleeding": False, "breathing_hard": True, "cold": False,
           "arms_ok": True, "walk": False},
}
DEFAULT = {"hurt": "", "broken": False, "bleeding": False, "breathing_hard": False, "cold": False,
           "arms_ok": True, "walk": True}


def persona(name):
    return PERSONAS.get(name, DEFAULT)


def answer(p, line):
    """The casualty's reply to one robot line (English), or None if it needs no answer."""
    t = " " + line.lower() + " "
    if "hear me" in t:
        return "Yes! Yes, I can hear you. Please help me."
    if "bleed" in t:
        return "Yes, it's bleeding, there's blood on my arm." if p["bleeding"] else "No, I don't think I'm bleeding."
    if "breath" in t:
        return "Yes... it's hard to breathe, there's so much dust." if p["breathing_hard"] else "No, I can breathe."
    if "cold" in t or " wet" in t:
        return "Yes, I'm so cold." if p["cold"] else "No, I'm okay."
    if "walk" in t or "stand" in t:
        return "Yes, I think I can walk." if p["walk"] else "No, I can't stand up."
    if "move your arms" in t or "arms and legs" in t:
        if p["arms_ok"] and p["broken"]:
            return "My arms, yes. Not my left leg, it hurts too much."
        return "Yes, I can move them." if p["arms_ok"] else "My legs yes. My arm hurts when I move it."
    if "hurt" in t or "where" in t or "injur" in t:
        if not p["hurt"]:
            return "No, I'm not hurt. I'm just stuck."
        return f"Yes, {p['hurt']}." + (" I think it's broken." if p["broken"] else "")
    if "?" in line:
        return "I don't know."
    return "Okay. Please hurry."
