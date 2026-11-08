"""G4: generation-bound evidence for a ground-route recheck after a sensed world change.

Standalone until the planner/permit integration handoff. Capture a CheckToken BEFORE starting an
async physics/permit/review operation, and return that same token with its completion. Looking up
the current token by route id when an old operation finishes would defeat this protection.

This guard publishes no permits or actions. A caller must also enforce L1, physics, seen-cell and
human gates. Reviews (including cached Gemini receipts) are audit references, never permission.
Create a new guard for a new scene/sensor clock. Signed-level routes need a level-aware observer;
they are rejected here rather than flattened onto the ground floor.
"""

from dataclasses import dataclass, field
from math import isfinite, pi

from planner.permit import MISS_AT, RES, walk


@dataclass(frozen=True)
class CheckToken:
    route: str
    generation: int
    attempt: int


@dataclass(frozen=True)
class Decision:
    ready: bool
    reason: str
    missing: tuple[tuple[int, int], ...] = ()


@dataclass
class _Check:
    token: CheckToken
    cells: frozenset[tuple[int, int]]
    verified: bool = False
    permitted: bool = False
    invalid: bool = False
    reviews: set[str] = field(default_factory=set)


def _finite(value):
    try:
        return type(value) in (int, float) and isfinite(value)
    except OverflowError:
        return False


class ShiftRecheck:
    def __init__(self, res=RES):
        if not _finite(res) or res <= 0:
            raise ValueError("resolution must be finite and positive")
        self.res = res
        self.generation = 0
        self._attempt = 0
        self._checks = {}
        self._last_sensor = float("-inf")
        self._boundary = float("-inf")
        self._free_at = {}

    def begin(self, route):
        rid, cells = route.get("id"), route.get("cells")
        if not isinstance(rid, str) or not rid or not isinstance(cells, (list, tuple)) or not cells:
            raise ValueError("a route id and nonempty ground cells are required")
        if any(not isinstance(c, (list, tuple)) or len(c) != 3
               or any(type(v) is not int for v in c) or c[2] != 0 for c in cells):
            raise ValueError("only integer ground cells are supported; levels must not be flattened")
        self._attempt += 1
        token = CheckToken(rid, self.generation, self._attempt)
        self._checks[rid] = _Check(token, frozenset((c[0], c[1]) for c in cells))
        return token

    def _current(self, token):
        check = self._checks.get(token.route)
        return check if (token.generation == self.generation and check
                         and check.token == token and not check.invalid) else None

    def on_world_change(self, data):
        t = data.get("t")
        self.generation += 1
        self._free_at.clear()
        self._checks.clear()
        if not _finite(t) or t < 0:
            self._boundary = float("inf")  # unknown chronology: fail closed until the guard is restarted
            raise ValueError("world change requires a finite nonnegative sensor-clock timestamp")
        # A late change notification cannot make a previously received frame become fresh.
        self._boundary = max(self._boundary, self._last_sensor, t)

    def verified(self, token, data):
        check = self._current(token)
        if check is None or data.get("id") != token.route:
            return False
        check.verified = data.get("ok") is True
        return check.verified

    def permitted(self, token, data):
        check = self._current(token)
        if check is None or data.get("route") != token.route:
            return False
        check.permitted = data.get("granted") is True
        return check.permitted

    def reviewed(self, token, receipt):
        check = self._current(token)
        if check is None or receipt.get("route") != token.route or not isinstance(receipt.get("id"), str):
            return False
        check.reviews.add(receipt["id"])
        return True

    def observe(self, data):
        """Accumulate measured free ray prefixes; misses and old/duplicate frames prove nothing."""
        t = data.get("t")
        pos = data.get("pose", {}).get("pos", [])
        ranges = data.get("lidar", [])
        if (not _finite(t) or t < 0 or t <= max(self._last_sensor, self._boundary)
                or not isinstance(pos, (list, tuple)) or len(pos) < 2
                or not all(_finite(v) for v in pos[:2])
                or not isinstance(ranges, (list, tuple)) or not ranges):
            return False
        self._last_sensor = t
        free, hits = set(), set()
        for k, distance in enumerate(ranges):
            if not _finite(distance) or not 0 < distance < MISS_AT:
                continue
            ray = walk(pos[0], pos[1], 2*pi*k/len(ranges), distance, self.res)
            hits.add(ray.pop())
            free.update(ray)
        for cell in hits:
            self._free_at.pop(cell, None)
        self._free_at.update({cell: t for cell in free - hits})
        for check in self._checks.values():
            if check.cells & hits:
                check.invalid = True  # a new obstacle requires a new check, not an old completion
        return bool(free or hits)

    def decision(self, token):
        check = self._current(token)
        if check is None:
            return Decision(False, "stale or obstructed check; start a new recheck")
        if not check.verified:
            return Decision(False, "physics verification is required")
        if not check.permitted:
            return Decision(False, "a matching L1 move permit is required")
        if self.generation:
            missing = tuple(sorted(c for c in check.cells if self._free_at.get(c, float("-inf")) <= self._boundary))
            if missing:
                return Decision(False, "post-change measured observations are required", missing)
        return Decision(True, "current physics, permit and required fresh observations agree")
