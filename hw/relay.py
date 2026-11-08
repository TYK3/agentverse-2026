"""Self-healing breadcrumb relay (L3): the Scout drops radio relays as it goes deeper, packets hop
back to the base outside, and the chain re-routes around a lost relay.

Radio: one Semtech SX1262 LoRa link per hop (docs/hardware.md, docs/electronics.md). Each hop's
delivery chance comes from a link budget: transmit power minus a log-distance path loss with a loss
per wall, against the receiver's sensitivity. A logistic curve turns the margin into a packet
delivery rate, and each hop retries a few times. Figures are marked source or assumed.

Behaviour:
- **Breadcrumbs.** When the Scout's best link back into the chain falls below DROP_MARGIN_DB, it drops
  the next relay it carries at its current position (it still has a usable link there).
- **Routing.** Packets take the most reliable path to the base (shortest path on -log(delivery)),
  so they may skip a hop, or go round a relay that died.
- **Self-healing.** `fail(node)` (crushed, flat battery) removes a relay; the next send re-routes.
- **Store and forward.** With no path at all, packets wait in a bounded buffer and go when a path
  returns. `status/link {"online": ...}` is published on every change, so the planner's offline mode
  (T15) takes over while the Scout is cut off.

`RelayTransport` wraps a bridge transport (hw/bridge.py): robot sources publish through the relay;
the hub side, at the base, subscribes to the inner transport directly.
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class RadioSpec:
    tx_dbm: float = 22.0           # source: SX1262 up to +22 dBm (Mouser SX1261/2 page)
    sensitivity_dbm: float = -123.0  # assumed: SF7 / 125 kHz (the -148 dBm sourced figure is SF12, too slow for map data)
    pl0_db: float = 40.0           # assumed: loss at 1 m, 868 MHz, antennas near the floor
    exponent: float = 3.5          # assumed: indoor log-distance exponent in a damaged building
    wall_db: float = 25.0          # assumed: per reinforced-concrete wall or rubble pile
    softness_db: float = 3.0       # assumed: width of the margin -> delivery curve
    retries: int = 2               # assumed: link-layer retries per hop
    airtime_s: float = 0.06        # assumed: one small packet at SF7
    notes: dict[str, str] = field(default_factory=lambda: {
        "tx_dbm": "source: SX1262 +22 dBm", "sensitivity_dbm": "assumed: SF7/125 kHz",
        "pl0_db": "assumed", "exponent": "assumed", "wall_db": "assumed", "retries": "assumed"})


P_MIN = 0.2            # a hop delivering less than this is not used
DROP_MARGIN_DB = 8.0   # drop a breadcrumb when the Scout's best link into the chain gets this thin
BUFFER = 500           # packets kept while cut off (oldest dropped first)


class Relay:
    def __init__(self, base: tuple[float, float, float], walls: Callable[[Any, Any], int],
                 crumbs: int = 4, spec: RadioSpec | None = None, seed: int = 0) -> None:
        self.spec = spec or RadioSpec()
        self.walls = walls
        self.rng = np.random.default_rng(seed)
        self.nodes: dict[str, tuple[float, float, float]] = {"base": tuple(base), "scout": tuple(base)}
        self.crumbs_left = crumbs
        self.dropped = 0
        self.buffer: deque = deque(maxlen=BUFFER)
        self.online: bool | None = None
        self.path: list[str] = []
        self.stats = {"sent": 0, "delivered": 0, "buffered": 0, "lost_hops": 0, "dropped_full": 0}
        self.log: list[str] = []
        self._cache: dict[tuple, float] = {}
        self.last_good: tuple | None = None

    # ---- radio model -----------------------------------------------------------------------
    def margin_db(self, a: str, b: str) -> float:
        pa, pb = self.nodes[a], self.nodes[b]
        d = max(0.1, math.dist(pa[:2], pb[:2]))
        s = self.spec
        loss = s.pl0_db + 10 * s.exponent * math.log10(d) + s.wall_db * self.walls(pa, pb)
        return s.tx_dbm - loss - s.sensitivity_dbm

    def delivery(self, a: str, b: str) -> float:
        """Chance one packet crosses hop a-b, retries included."""
        key = (a, b, self.nodes[a], self.nodes[b])
        if len(self._cache) > 5000:  # the Scout keeps moving: forget old positions
            self._cache.clear()
        if key not in self._cache:
            once = 1.0 / (1.0 + math.exp(-self.margin_db(a, b) / self.spec.softness_db))
            self._cache[key] = 1.0 - (1.0 - once) ** (self.spec.retries + 1)
        return self._cache[key]

    # ---- chain -------------------------------------------------------------------------------
    def route(self) -> list[str]:
        """Most reliable path scout -> base over usable hops, or [] when cut off."""
        names = list(self.nodes)
        best = {n: math.inf for n in names}
        prev: dict[str, str] = {}
        best["scout"] = 0.0
        heap = [(0.0, "scout")]
        while heap:
            cost, n = heapq.heappop(heap)
            if n == "base":
                break
            if cost > best[n]:
                continue
            for m in names:
                if m == n:
                    continue
                p = self.delivery(n, m)
                if p < P_MIN:
                    continue
                c = cost - math.log(p)
                if c < best[m]:
                    best[m], prev[m] = c, n
                    heapq.heappush(heap, (c, m))
        if best["base"] == math.inf:
            return []
        path, n = ["base"], "base"
        while n != "scout":
            n = prev[n]
            path.append(n)
        return path[::-1]

    def best_margin(self, pos=None) -> float:
        """The Scout's (or a point's) best link margin into the rest of the chain, dB."""
        saved = self.nodes["scout"]
        if pos is not None:
            self.nodes["scout"] = tuple(pos)
        try:
            return max(self.margin_db("scout", n) for n in self.nodes if n != "scout")
        finally:
            self.nodes["scout"] = saved

    def step(self, t: float, scout_pos) -> list[tuple[str, dict]]:
        """Move the Scout, drop a breadcrumb if its link is thinning, re-route. Returns status/link changes.

        A link can fall off a cliff at a corner (one more wall), so the crumb goes down at the last
        spot on the way where the margin was still healthy, like a robot that checks as it drives.
        """
        pos = tuple(float(v) for v in scout_pos)
        self.nodes["scout"] = pos
        margin = self.best_margin()
        if margin >= DROP_MARGIN_DB:
            self.last_good = pos
        elif self.crumbs_left > 0 and self.last_good is not None and self.last_good != pos:
            self.dropped += 1
            self.crumbs_left -= 1
            name = f"relay{self.dropped}"
            self.nodes[name] = self.last_good
            self.log.append(f"{t:.1f}s dropped {name} at ({self.last_good[0]:.2f}, {self.last_good[1]:.2f}) "
                            f"(margin here {margin:.1f} dB)")
            self.last_good = pos if self.best_margin() >= DROP_MARGIN_DB else None
        self.path = self.route()
        return self._status(t)

    def fail(self, node: str, t: float = 0.0) -> list[tuple[str, dict]]:
        """A relay is lost (crushed by debris, flat battery): the chain heals around it if it can."""
        if node in ("base", "scout") or node not in self.nodes:
            return []
        del self.nodes[node]
        self._cache.clear()
        self.log.append(f"{t:.1f}s lost {node}")
        self.path = self.route()
        return self._status(t)

    def _status(self, t: float) -> list[tuple[str, dict]]:
        online = bool(self.path)
        if online == self.online:
            return []
        self.online = online
        self.log.append(f"{t:.1f}s link {'up via ' + '>'.join(self.path) if online else 'cut off'}")
        return [("status/link", {"online": online})]

    # ---- packets -----------------------------------------------------------------------------
    def send(self, packet: Any) -> list[Any]:
        """Queue a packet and try to forward everything waiting. Returns the packets that reached base."""
        self.stats["sent"] += 1
        if len(self.buffer) == BUFFER:
            self.stats["dropped_full"] += 1  # the deque drops the oldest
        self.buffer.append(packet)
        return self.flush()

    def flush(self) -> list[Any]:
        out = []
        if not self.path:
            self.stats["buffered"] = len(self.buffer)
            return out
        hops = list(zip(self.path, self.path[1:], strict=False))
        keep: deque = deque(maxlen=BUFFER)
        while self.buffer:
            pkt = self.buffer.popleft()
            if all(self.rng.random() < self.delivery(a, b) for a, b in hops):
                out.append(pkt)
                self.stats["delivered"] += 1
            else:
                self.stats["lost_hops"] += 1
                keep.append(pkt)  # store and forward: try again on the next flush
        self.buffer = keep
        self.stats["buffered"] = len(self.buffer)
        return out

    def status(self) -> dict[str, Any]:
        return {"online": bool(self.path), "path": list(self.path), "relays": [n for n in self.nodes
                if n.startswith("relay")], "crumbs_left": self.crumbs_left, **self.stats}


class RelayTransport:
    """A bridge transport whose robot side goes through the relay chain (hw/bridge.py interface)."""

    def __init__(self, inner: Any, relay: Relay) -> None:
        self.inner, self.relay = inner, relay

    def publish(self, topic: str, payload: bytes) -> None:
        for t, p in self.relay.send((topic, payload)):
            self.inner.publish(t, p)

    def flush(self) -> None:
        for t, p in self.relay.flush():
            self.inner.publish(t, p)

    def subscribe(self, pattern: str, fn) -> None:
        self.inner.subscribe(pattern, fn)  # the hub listens at the base

    def close(self) -> None:
        self.inner.close()
