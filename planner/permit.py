"""Proof-carrying move permits (L1): the Responder may move along a route only while the evidence holds.

A route earns its permit when the physics check passes (`route/verified ok`). The permit is revoked
the moment the robots *sense* a change on it, never on sim truth:
- the Scout's LiDAR returns a hit inside a route cell (rubble shifted into the path), or
- perception reports a hazard (`at_risk`, `collapsed`, or an L5 exclusion) on a route cell.
It is re-earned only by fresh observation: every route cell must be crossed by a LiDAR ray that ends
beyond it (seen free) after the shift, with no new hit and no hazard on the route. There is no timer.
While revoked, the planner sends the Scout to re-look: at the shifted cells, else the hazard, else
the nearest route cell not yet seen free again. The newest revoked route re-sends its re-look every
RELOOK_EVERY_S until it is re-earned, because other Scout moves (the Explorer's frontiers, L2) can
take the Scout away before it gets there (#52: a permit was never re-earned and the Responder froze).

Every change goes out as `permit/route` with its evidence list, and as `log/decision` so the
reasoning panel shows it. `Permits.on_*` return the (topic, payload) pairs to publish.
"""

from __future__ import annotations

import math
from typing import Any

RES = 0.05             # perception's grid (cell = floor(coordinate / RES)); routes use (i, j)
HITS_TO_REVOKE = 2     # LiDAR hits inside the route needed to call it a shift (one can be noise)
MISS_AT = 6.0          # a LiDAR range at or past this is "no return" (sim/sensors.py MAX_RANGE)
BAD_HAZARDS = ("at_risk", "collapsed")
RELOOK_EVERY_S = 8.0   # a revoked route re-sends its re-look this often until it is re-earned


def columns(cells) -> list[tuple[int, int]]:
    out, seen = [], set()
    for c in cells:
        ij = (int(c[0]), int(c[1]))
        if ij not in seen:
            seen.add(ij)
            out.append(ij)
    return out


def walk(x0, y0, angle, length, res=RES):
    """(i, j) columns a ray from (x0, y0) crosses up to `length` m, in order (grid traversal, no sampling)."""
    dx, dy = math.cos(angle), math.sin(angle)
    i, j = math.floor(x0 / res), math.floor(y0 / res)
    step_i, step_j = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
    nx = ((i + (step_i > 0)) * res - x0) / dx if abs(dx) > 1e-12 else math.inf
    ny = ((j + (step_j > 0)) * res - y0) / dy if abs(dy) > 1e-12 else math.inf
    tx, ty = (res / abs(dx) if abs(dx) > 1e-12 else math.inf), (res / abs(dy) if abs(dy) > 1e-12 else math.inf)
    out = [(i, j)]
    while min(nx, ny) < length:
        if nx < ny:
            i, nx = i + step_i, nx + tx
        else:
            j, ny = j + step_j, ny + ty
        out.append((i, j))
    return out


def trace(x0, y0, lidar, res=RES):
    """({column: hit count}, {columns seen free}) for one horizontal LiDAR sweep from (x0, y0).

    Ray k points at 2*pi*k/n in the scene frame (coord/CONTRACT.md). Cells a ray passes before its
    return are seen free; the cell holding the return is a hit; a miss sees free out to MISS_AT.
    """
    n = len(lidar)
    hits: dict[tuple[int, int], int] = {}
    free: set[tuple[int, int]] = set()
    for k, r in enumerate(lidar):
        miss = r >= MISS_AT - 1e-9
        cells = walk(x0, y0, 2 * math.pi * k / n, MISS_AT if miss else r, res)
        if not miss:
            last = cells.pop()
            hits[last] = hits.get(last, 0) + 1
        free.update(cells)
    return hits, free


class Permit:
    def __init__(self, route_id: str, cells) -> None:
        self.route = route_id
        self.cols = columns(cells)
        self.colset = set(self.cols)
        self.granted = False
        self.verified = False
        self.revoked_at: float | None = None
        self.shift: dict[tuple[int, int], int] = {}     # column -> LiDAR hits seen inside it
        self.hazards: dict[tuple[int, int], str] = {}   # column -> why
        self.reseen: set[tuple[int, int]] = set()       # columns seen free since the shift
        self.evidence: list[dict[str, Any]] = []
        self.relook_at = -math.inf                      # when its last re-look scout/goto went out

    def message(self, t: float, reason: str) -> dict[str, Any]:
        return {"route": self.route, "granted": self.granted, "t": round(t, 2), "reason": reason,
                "evidence": list(self.evidence)}


class Permits:
    def __init__(self, res: float = RES) -> None:
        self.res = res
        self.proposed: dict[str, list] = {}
        self.pending_verified: dict[str, tuple[dict[str, Any], float]] = {}
        self.permits: dict[str, Permit] = {}
        self.hazards: dict[tuple[int, int], dict] = {}

    # ---- inputs ----------------------------------------------------------------------------
    def on_route_proposed(self, data: dict[str, Any]) -> list:
        route_id = data["id"]
        self.proposed[route_id] = data["cells"]
        pending = self.pending_verified.pop(route_id, None)
        return self.on_route_verified(*pending) if pending else []

    def on_route_verified(self, data: dict[str, Any], t: float) -> list:
        cells = self.proposed.get(data["id"])
        if cells is None:
            # A sim-first subscriber may publish its verdict before our route/proposed
            # subscriber runs. Keep the verdict inert until the matching cells arrive.
            self.pending_verified[data["id"]] = (data, t)
            return []
        p = self.permits[data["id"]] = Permit(data["id"], cells)
        if not data.get("ok"):
            p.evidence = [_ev("verified", f"physics check failed: {data.get('detail') or 'unstable cells'}", t)]
            return self._out(p, t, "physics check failed")
        p.verified = True
        p.evidence = [_ev("verified", f"physics check passed for {len(p.cols)} cells", t)]
        on_route = self._hazards_on(p)
        if on_route:
            p.hazards = on_route
            p.evidence.append(_ev("hazard", _hazard_text(on_route), t))
            p.revoked_at = t
            return self._out(p, t, "a sensed hazard is on the route") + self._relook(p, t)
        p.granted = True
        p.evidence.append(_ev("clear", "no sensed hazard on the route", t))
        return self._out(p, t, "verified and clear")

    def on_hazards(self, data: list[dict[str, Any]], t: float) -> list:
        self.hazards = {(h["cell"][0], h["cell"][1]): h for h in data
                        if h.get("status") in BAD_HAZARDS or h.get("exclusion")}
        out = []
        for p in self.permits.values():
            on_route = self._hazards_on(p)
            if on_route and p.granted:
                p.hazards = on_route
                out += self._revoke(p, t, _ev("hazard", _hazard_text(on_route), t))
            else:
                p.hazards = on_route
                out += self._try_regrant(p, t)
        return out

    def on_sensors(self, data: dict[str, Any], t: float) -> list:
        """Trace the Scout's LiDAR: hits inside a route are shifts; rays through it are fresh looks."""
        lidar = data.get("lidar") or []
        if not lidar or not self.permits:
            return []
        x0, y0 = data["pose"]["pos"][0], data["pose"]["pos"][1]
        hits, free = trace(x0, y0, lidar, self.res)
        out = []
        for p in self.permits.values():
            if not p.verified:
                continue
            inside = {c: h for c, h in hits.items() if c in p.colset}
            if p.granted:
                for c, h in inside.items():
                    p.shift[c] = p.shift.get(c, 0) + h
                if sum(p.shift.values()) >= HITS_TO_REVOKE:
                    cells = sorted(p.shift)
                    out += self._revoke(p, t, _ev("shift", f"LiDAR hit inside the route at {len(cells)} "
                                                           f"cell(s), first {list(cells[0])}", t))
                continue
            if p.revoked_at is None:
                continue
            if p.hazards:  # looks taken while a hazard is still reported do not count
                p.reseen = set()
                continue
            if inside:  # still something in the way: those cells must be looked at again
                p.reseen -= set(inside)
                p.shift.update({c: p.shift.get(c, 0) + h for c, h in inside.items()})
            p.reseen |= (free & p.colset) - set(inside)
            out += self._try_regrant(p, t)
        return out + self._keep_relooking(t, (x0, y0))

    def _keep_relooking(self, t: float, scout_xy) -> list:
        """The newest revoked route re-sends its re-look until it is re-earned (one route drives the Scout)."""
        waiting = [p for p in self.permits.values() if p.verified and not p.granted and p.revoked_at is not None]
        if not waiting:
            return []
        p = waiting[-1]
        if t - p.relook_at < RELOOK_EVERY_S:
            return []
        return self._relook(p, t, scout_xy)

    # ---- decisions -------------------------------------------------------------------------
    def _revoke(self, p: Permit, t: float, why: dict) -> list:
        p.granted, p.revoked_at, p.reseen = False, t, set()
        p.evidence.append(why)
        return self._out(p, t, f"revoked: {why['detail']}") + self._relook(p, t)

    def _try_regrant(self, p: Permit, t: float) -> list:
        if p.granted or not p.verified or p.revoked_at is None or p.hazards:
            return []
        if not p.colset <= p.reseen:
            return []
        p.granted, p.shift = True, {}
        p.evidence.append(_ev("fresh_scan", f"all {len(p.cols)} route cells seen free by LiDAR after the "
                                            f"change at {p.revoked_at:.1f}s", t))
        p.revoked_at = None
        return self._out(p, t, "re-earned by a fresh scan")

    def _relook(self, p: Permit, t: float, scout_xy=None) -> list:
        """Send the Scout to look again: the first shifted cell, else the first hazard cell, else the route
        cell not yet seen free again nearest the Scout."""
        target = sorted(p.shift) or sorted(p.hazards)
        if target:
            i, j = target[0]
        else:
            unseen = [c for c in p.cols if c not in p.reseen]
            if not unseen:
                return []
            sx, sy = scout_xy if scout_xy else ((unseen[0][0] + 0.5) * self.res, (unseen[0][1] + 0.5) * self.res)
            i, j = min(unseen, key=lambda c: math.hypot((c[0] + 0.5) * self.res - sx, (c[1] + 0.5) * self.res - sy))
        p.relook_at = t
        return [("scout/goto", {"target": [round((i + 0.5) * self.res, 3), round((j + 0.5) * self.res, 3), 0.075],
                                "reason": f"re-look to re-earn move permission on route {p.route}"})]

    def _hazards_on(self, p: Permit) -> dict:
        return {c: self.hazards[c].get("why", "hazard") for c in p.colset if c in self.hazards}

    def _out(self, p: Permit, t: float, reason: str) -> list:
        msg = p.message(t, reason)
        log = {"t": round(t, 2), "perception": "; ".join(e["detail"] for e in p.evidence[-2:]),
               "model": "local permit rule", "physics": "ok" if p.verified else "failed",
               "outcome": "permit granted" if p.granted else "permit revoked",
               "reason": f"route {p.route}: {reason}"}
        return [("permit/route", msg), ("log/decision", log)]

    def granted(self, route_id: str) -> bool:
        p = self.permits.get(route_id)
        return bool(p and p.granted)


def _ev(kind: str, detail: str, t: float) -> dict[str, Any]:
    return {"kind": kind, "detail": detail, "t": round(t, 2)}


def _hazard_text(on_route: dict) -> str:
    cells = sorted(on_route)
    return f"sensed hazard on {len(cells)} route cell(s), first {list(cells[0])}: {on_route[cells[0]]}"


def start(bus, clock=None):
    """Wire the permits to the hub; publishes permit/route only once the topic is in the contract."""
    import time

    t0 = time.monotonic()
    now = clock or (lambda: time.monotonic() - t0)
    permits = Permits()
    try:
        from coord import messages
        topics = set(messages.TOPICS)
    except ImportError:
        topics = set()

    async def emit(pairs):
        for topic, payload in pairs:
            if topic in topics:
                await bus.publish(topic, payload)

    async def proposed(d):
        await emit(permits.on_route_proposed(d))

    bus.subscribe("route/proposed", proposed)

    async def verified(d):
        await emit(permits.on_route_verified(d, now()))

    async def hazards(d):
        await emit(permits.on_hazards(d, now()))

    async def sensors(d):
        await emit(permits.on_sensors(d, now()))

    bus.subscribe("route/verified", verified)
    bus.subscribe("map/hazards", hazards)
    bus.subscribe("sensors/scout", sensors)
    return permits
