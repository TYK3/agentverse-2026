"""Y2: pick what the Responder brings a casualty: a kit item, or found material from the rubble.

Two local parts, no Gemini call:

1. `choose(injuries, kit, board)`: the casualty's injuries (Y3's `casualty/triage`, or `injuries` on a
   `map/casualties` entry, or the guide's self-reported answers; any list of short strings) map to
   the item that treats the most urgent one (NEEDS, in order: bleeding, fracture, cold, thirst, then
   general first aid and a radio to talk). A kit item still on the deck is used first. A fracture
   with no kit splint left uses a found board if the Scout has sensed one; otherwise the first aid
   kit. No injury known -> None, and the caller keeps its own default.

2. `BoardFinder`: searches the Scout's own depth points (`sensors/scout.points`) for loose debris
   usable as a splint: a low, long, thin footprint on the floor (a plank or a pole). Points are binned
   into the map's 0.05 m plan columns keeping each column's highest point; columns topping out
   between FLOOR_Z and LOW_Z are low objects (a wall's column tops out far higher). Connected low
   columns whose footprint is LENGTH_M long and at most WIDTH_M wide are a board. Its mass is
   estimated from the sensed volume at pine density and must fit the arm's 0.5 kg payload.

   The responder/action contract names blocks by id, so a sensed board is named by the nearest
   `scene/loaded` block within NAME_M of its centre. That is only a label for the sim's grip weld (a
   real arm picks the grasp from its own camera): where the board is, how big and how heavy, comes
   from the Scout's points alone. Without depth points (Y9 not wired yet) nothing is found and a
   fracture gets the kit splint or the first aid kit.
"""

from __future__ import annotations

import math
from collections import deque

RES = 0.05
KIT = ("water", "first_aid_kit", "radio", "bandage", "splint", "thermal_blanket")
FLOOR_Z = 0.03            # points below this are the floor (perception/cloud.py)
LOW_Z = 0.10              # a column topping out below this is a low object lying on the floor
MIN_POINTS = 2            # points a column needs before it counts
LENGTH_M = (0.3, 0.7)     # a usable splint: forearm or shin length
WIDTH_M = 0.12            # and narrow enough to bind to a limb
WOOD_KG_M3 = 450          # pine
ARM_PAYLOAD_KG = 0.5      # docs/hardware.md: Kinova Gen3 lite rated payload
NAME_M = 0.15             # a scene/loaded block this close to the sensed centre names it

# (need, item, words that point to it), most urgent first.
NEEDS = (
    ("bleeding", "bandage", ("bleed", "blood", "cut", "wound", "lacerat", "gash")),
    ("fracture", "splint", ("fractur", "broken", "break", "deform", "dislocat", "sprain")),
    ("cold", "thermal_blanket", ("cold", "hypotherm", "shiver", "shock", "wet", "freez")),
    ("thirst", "water", ("thirst", "dehydrat", "dry mouth", "water")),
    ("injury", "first_aid_kit", ("burn", "pain", "hurt", "injur", "bruis")),
    ("alone", "radio", ("alone", "scared", "panic", "talk", "frighten")),
)


def needs_of(injuries):
    """Needs named by the injury strings, most urgent first (each once)."""
    text = " ".join(str(i).lower() for i in injuries or ())
    return [(need, item) for need, item, words in NEEDS if any(w in text for w in words)]


def choose(injuries, kit, board=None):
    """-> {"item", "block", "need", "source": "kit" | "found" | "fallback", "why"} or None if nothing
    is known about the casualty's injuries. `kit` is the items still on the deck; `board` a sensed
    board from BoardFinder.best() (with a "block" name) or None."""
    needs = needs_of(injuries)
    if not needs:
        return None
    for need, item in needs:
        if item in kit:
            return {"item": item, "block": None, "need": need, "source": "kit",
                    "why": f"{need}: kit {item.replace('_', ' ')}"}
        if item == "splint" and board and board.get("block"):
            return {"item": "splint", "block": board["block"], "need": need, "source": "found",
                    "why": (f"{need}: no kit splint left; found board {board['block']} "
                            f"{board['length']:.2f} m x {board['width']:.2f} m, ~{board['kg']:.2f} kg, "
                            f"sensed at [{board['pos'][0]:.2f}, {board['pos'][1]:.2f}]")}
    need = needs[0][0]
    if "first_aid_kit" in kit:
        return {"item": "first_aid_kit", "block": None, "need": need, "source": "fallback",
                "why": f"{need}: {needs[0][1].replace('_', ' ')} used up and no usable debris sensed; first aid kit"}
    return None


class BoardFinder:
    """Accumulates the Scout's depth points and finds boards lying on the floor."""

    def __init__(self, res=RES):
        self.res = res
        self.top = {}        # (i, j) -> highest point z seen in that plan column
        self.count = {}      # (i, j) -> points seen
        self.blocks = []     # scene/loaded blocks, only to name a sensed board for the grip weld
        self.taken = set()   # block ids already carried away

    def on_scene(self, data):
        self.blocks = list(data.get("blocks", []))

    def add(self, points):
        for x, y, z in points:
            if z < FLOOR_Z:
                continue
            c = (math.floor(x / self.res), math.floor(y / self.res))
            self.top[c] = max(self.top.get(c, z), z)
            self.count[c] = self.count.get(c, 0) + 1

    def on_sensors(self, data):
        if data.get("points"):
            self.add(data["points"])

    def _components(self):
        low = {c for c, z in self.top.items() if z < LOW_Z and self.count[c] >= MIN_POINTS}
        tall = {c for c, z in self.top.items() if z >= LOW_Z}
        seen, out = set(), []
        for start in sorted(low):
            if start in seen:
                continue
            comp, queue = [], deque([start])
            seen.add(start)
            while queue:
                i, j = queue.popleft()
                comp.append((i, j))
                for di in (-1, 0, 1):
                    for dj in (-1, 0, 1):
                        n = (i + di, j + dj)
                        if n in low and n not in seen:
                            seen.add(n)
                            queue.append(n)
            touches_tall = any((i + di, j + dj) in tall for i, j in comp for di in (-1, 0, 1) for dj in (-1, 0, 1))
            if not touches_tall:          # low columns at a wall's foot are part of the wall or a pile
                out.append(comp)
        return out

    def boards(self):
        """Every sensed board: {"pos", "length", "width", "height", "kg", "axis_deg", "block"}."""
        found = []
        for comp in self._components():
            xs = [(i + 0.5) * self.res for i, _ in comp]
            ys = [(j + 0.5) * self.res for _, j in comp]
            cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
            sxx = sum((x - cx) ** 2 for x in xs)
            syy = sum((y - cy) ** 2 for y in ys)
            sxy = sum((x - cx) * (y - cy) for x, y in zip(xs, ys, strict=True))
            ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
            ux, uy = math.cos(ang), math.sin(ang)
            along = [(x - cx) * ux + (y - cy) * uy for x, y in zip(xs, ys, strict=True)]
            across = [-(x - cx) * uy + (y - cy) * ux for x, y in zip(xs, ys, strict=True)]
            length = max(along) - min(along) + self.res
            width = max(across) - min(across) + self.res
            height = max(self.top[c] for c in comp)
            if not (LENGTH_M[0] <= length <= LENGTH_M[1] and width <= WIDTH_M):
                continue
            # Binning into 0.05 m columns overstates each footprint side by up to one cell, so the volume
            # estimate takes one cell off each (never below half a cell); the height is the top point.
            kg = (length - self.res) * max(width - self.res, self.res / 2) * height * WOOD_KG_M3
            found.append({"pos": [round(cx, 3), round(cy, 3), round(height / 2, 3)], "length": round(length, 3),
                          "width": round(width, 3), "height": round(height, 3), "kg": round(kg, 3),
                          "axis_deg": round(math.degrees(ang), 1), "block": self._name(cx, cy)})
        return found

    def _name(self, x, y):
        best = None
        for b in self.blocks:
            if b["id"] in self.taken:
                continue
            d = math.hypot(b["pos"][0] - x, b["pos"][1] - y)
            if d <= NAME_M and (best is None or d < best[0]):
                best = (d, b["id"])
        return best[1] if best else None

    def best(self, near=None):
        """The liftable, named board nearest `near` (x, y), or the first one; None if none."""
        ok = [b for b in self.boards() if b["block"] and b["kg"] <= ARM_PAYLOAD_KG]
        if not ok:
            return None
        if near is None:
            return ok[0]
        return min(ok, key=lambda b: math.hypot(b["pos"][0] - near[0], b["pos"][1] - near[1]))
