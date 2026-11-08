"""Casualty dialogue (L2): call out, listen for tapping, move, listen again, narrow the location.

Offline: no model calls. The Scout hears a faint sound; the listener
1. calls out through the Scout's speaker (`say` to the casualty): "If you can hear me, tap three times.",
2. listens for LISTEN_S and takes the tapping's bearing from here (circular mean of loud samples),
3. drives to a second listening spot SPOT_M across that bearing (a seen, free cell of the live map,
   sent as `scout/goto`, which the explorer honours as an outside target),
4. calls again, takes a second bearing and intersects the two rays: a position plus an uncertainty
   radius from the bearing noise and how sharply the rays cross,
5. if the rays cross too shallowly, tries a third spot once, then tells the casualty help is coming.

The sound bearings it causes also reach `perception/casualties.py` on their own (loud samples from
poses at least 1 m apart are triangulated there), so the casualty's confidence rises with no edits
to that file. `Listener.estimate` is the dialogue's own result, for the log and the paramedic report.

`Listener.on_sensors(data, t)` takes `sensors/scout` and returns the (topic, payload) pairs to publish.
"""

from __future__ import annotations

import math
from typing import Any

from perception.grid import cell_of

HEAR = 0.08            # acoustic level that starts a dialogue
LOUD = 0.25            # level of a tap worth taking a bearing from
LISTEN_S = 4.0         # listening window after each call
MIN_SAMPLES = 3        # loud samples needed for a bearing
SPOT_M = 1.2           # second spot this far across the first bearing
ARRIVE_S = 20.0        # give up on reaching a spot after this long
MIN_CROSS = math.radians(15.0)   # shallower crossings amplify bearing noise; try another spot
BEARING_SIGMA = math.radians(5.0)  # 1-sigma bearing noise of a tap (ReSpeaker DOA, docs/hardware.md)
RETRY_S = 30.0         # after a dialogue with no fix, wait this long before calling again
RETRY_FOUND_S = 120.0  # after a fix: the Scout gets on with mapping
CLEARANCE = 0.15       # a listening spot needs this much seen free space around it

CALL = "Hello? Is anyone there? If you can hear me, tap three times on something hard."
CALL_AGAIN = "I moved. Please tap three times again, I am listening."
FOUND = "I can hear you. I know where you are. Help is coming. Tap now and then so we can find you."
NO_TAP = "If you can hear me and cannot tap, shout. I will keep listening."


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def circular_mean(angles: list[float]) -> float:
    return math.atan2(sum(math.sin(a) for a in angles), sum(math.cos(a) for a in angles))


def intersect(p, a, q, b):
    """Point where ray (p, angle a) meets ray (q, angle b), both forward; None if parallel or behind."""
    d = math.cos(a) * math.sin(b) - math.sin(a) * math.cos(b)
    if abs(d) < 1e-9:
        return None
    dx, dy = q[0] - p[0], q[1] - p[1]
    s = (dx * math.sin(b) - dy * math.cos(b)) / d
    u = (dx * math.sin(a) - dy * math.cos(a)) / d
    if s <= 0 or u <= 0:
        return None
    return (p[0] + s * math.cos(a), p[1] + s * math.sin(a))


def uncertainty(p, q, x, crossing):
    """1-sigma position error radius of a two-ray fix (m)."""
    r = max(math.dist(p, x), math.dist(q, x))
    return r * BEARING_SIGMA / max(math.sin(crossing), 1e-3)


class Listener:
    def __init__(self, grid=None) -> None:
        self.grid = grid
        self.state = "idle"     # idle | listening | moving
        self.rays: list[tuple[tuple[float, float], float]] = []   # (xy, scene bearing) per spot
        self.samples: list[float] = []
        self.until = 0.0
        self.target = None
        self.tried_spots = 0
        self.estimate: dict[str, Any] | None = None
        self.log: list[str] = []
        self.ended = -math.inf
        self.pose = None

    @property
    def active(self) -> bool:
        return self.state in ("listening", "moving")

    def on_sensors(self, data: dict[str, Any], t: float) -> list[tuple[str, dict]]:
        pose = data["pose"]
        self.pose = (pose["pos"], pose["yaw"])
        ac = data.get("acoustic") or {}
        level = float(ac.get("level", 0.0))
        out: list[tuple[str, dict]] = []
        if self.state == "idle":
            if level >= HEAR and t - self.ended >= RETRY_S:
                self.rays, self.tried_spots, self.estimate = [], 0, None
                out += self._call(CALL, t, f"heard a sound (level {level:.2f})")
        elif self.state == "listening":
            if level >= LOUD:
                self.samples.append(wrap(pose["yaw"] + math.radians(ac["bearing"])))
            if t >= self.until:
                out += self._heard(t)
        elif self.state == "moving":
            motion = (data.get("motion") or {}).get("state")
            if motion in ("arrived", "blocked") or t >= self.until:
                out += self._call(CALL_AGAIN, t, f"at listening spot {len(self.rays) + 1} ({motion or 'timeout'})")
        return out

    # ---- steps ---------------------------------------------------------------------------
    def _call(self, text, t, why):
        self.state, self.samples, self.until = "listening", [], t + LISTEN_S
        self.log.append(f"{t:.1f}s call: {why}")
        return [("say", {"to": "casualty", "intent": "reassure", "text": text, "lang": "auto"})]

    def _heard(self, t):
        pos, _ = self.pose
        if len(self.samples) < MIN_SAMPLES:
            self.log.append(f"{t:.1f}s no tapping heard ({len(self.samples)} loud samples)")
            return self._end(t, NO_TAP)
        bearing = circular_mean(self.samples)
        self.rays.append(((pos[0], pos[1]), bearing))
        self.log.append(f"{t:.1f}s tapping at bearing {math.degrees(bearing):.0f} deg from "
                        f"({pos[0]:.2f}, {pos[1]:.2f}), {len(self.samples)} taps")
        if len(self.rays) >= 2:
            fix = self._fix()
            if fix is not None:
                self.estimate = fix
                self.log.append(f"{t:.1f}s located at ({fix['pos'][0]:.2f}, {fix['pos'][1]:.2f}) "
                                f"+/- {fix['radius_m']:.2f} m")
                return self._end(t, FOUND)
        if self.tried_spots >= 2:
            return self._end(t, FOUND if self.rays else NO_TAP)
        return self._move(t)

    def _move(self, t):
        pos, _ = self.pose
        spot = self._spot()
        self.tried_spots += 1
        if spot is None:
            self.log.append(f"{t:.1f}s no free listening spot within {SPOT_M} m")
            return self._end(t, FOUND)
        self.state, self.until, self.target = "moving", t + ARRIVE_S, spot
        target = [round(spot[0], 3), round(spot[1], 3), pos[2]]
        bearing = math.degrees(self.rays[-1][1])
        return [("scout/goto", {"target": target,
                                "reason": f"listen again from a 2nd spot: tapping heard at bearing {bearing:.0f} deg"})]

    def _end(self, t, text):
        # Back to idle; a located casualty waits longer before the Scout calls out again.
        self.state, self.target = "idle", None
        self.ended = t + (RETRY_FOUND_S - RETRY_S if self.estimate else 0.0)
        return [("say", {"to": "casualty", "intent": "reassure", "text": text, "lang": "auto"})]

    def _fix(self):
        """Best crossing among the rays so far."""
        best = None
        for i in range(len(self.rays)):
            for j in range(i + 1, len(self.rays)):
                (p, a), (q, b) = self.rays[i], self.rays[j]
                crossing = abs(wrap(a - b))
                crossing = min(crossing, math.pi - crossing)
                if crossing < MIN_CROSS:
                    continue
                x = intersect(p, a, q, b)
                if x is None:
                    continue
                r = uncertainty(p, q, x, crossing)
                if best is None or r < best["radius_m"]:
                    best = {"pos": [round(x[0], 3), round(x[1], 3)], "radius_m": round(r, 3),
                            "crossing_deg": round(math.degrees(crossing), 1), "spots": len(self.rays),
                            "clues": ["sound"], "how": "two tapping bearings from different spots"}
        return best

    def _spot(self):
        """A seen, free listening spot SPOT_M across the last bearing (either side), else None."""
        (px, py), bearing = self.rays[-1]
        z = self.pose[0][2]
        sides = (1, -1) if len(self.rays) % 2 else (-1, 1)  # a third spot goes to the other side
        for dist in (SPOT_M, 0.8 * SPOT_M, 0.6 * SPOT_M):
            for side in sides:
                a = bearing + side * math.pi / 2
                x, y = px + dist * math.cos(a), py + dist * math.sin(a)
                if self._free(x, y, z):
                    return (x, y)
        return None

    def _free(self, x, y, z):
        if self.grid is None:
            return True
        res = self.grid.res
        n = math.ceil(CLEARANCE / res)
        ci, cj, ck = cell_of((x, y, z), res)
        for di in range(-n, n + 1):
            for dj in range(-n, n + 1):
                cur = self.grid.cells.get((ci + di, cj + dj, ck))
                if cur is None or cur["state"] != "seen" or cur["occupied"]:
                    return False
        return True
