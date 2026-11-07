"""Casualty detection: thermal, sound and (optionally) vision fused into map/casualties, no faces (T10).

Thermal: the strongest connected region of the 16x12 grid above 0.6 gives a bearing (camera field of
view 60 degrees across), and the LiDAR range along that bearing gives a point.
Sound: the acoustic bearing, averaged over the last 5 samples (circular mean, in the scene frame).
Fusion: rays (Scout position, scene bearing) from poses at least 1 m apart are intersected; the
median of the intersections is the position, or the median thermal point while there is no pair.
Confidence = 0.4*thermal + 0.3*sound + 0.3*vision, each clue scored 0..1.
Vision: the camera frame goes to gemini-3.8-flash through coord/gem.py, at most once a second and
only when thermal or sound already suggests someone. With GEMINI_MODE=off (or no coord/gem.py) it is
skipped and marked as a stand-in. The frame is dropped right after the call: never stored or sent.
"""

import json
import math
import statistics
import time
from collections import deque

THERMAL_W, THERMAL_H = 16, 12
FOV_H = math.radians(60.0)
HOT = 0.6             # thermal region threshold
BACKGROUND = 0.1
THERMAL_MAX_RANGE = 4.5
SOUND_FLOOR = 0.1     # averaged level above this is a sound clue
SOUND_FULL = 0.3      # averaged level that scores 1
AVERAGE = 5           # acoustic samples in the moving average
BASELINE = 1.0        # metres between two Scout poses before their rays are intersected
MIN_ANGLE = math.radians(30.0)   # rays crossing at a shallower angle amplify bearing noise
MERGE = 0.6           # metres: points this close are the same casualty
VISION_PERIOD = 1.0   # seconds between vision calls
VITALS = {"breathing_rate": 14, "simulated": True}
PROMPT = ('Is there a person-shaped figure lying or sitting in this image? Answer JSON only: '
          '{"person": bool, "bbox": [x,y,w,h], "posture": "lying|sitting|standing|unknown"}. '
          'Do not describe faces.')

try:
    from coord import gem
except ImportError:   # coord/gem.py (T26) not merged yet: vision is a stand-in
    gem = None


def thermal_region(grid):
    """(peak, column) of the hottest 4-connected region above HOT whose peak is off the image edge, or None."""
    rows, cols = len(grid), len(grid[0])
    seen, best = set(), None
    for r in range(rows):
        for c in range(cols):
            if grid[r][c] <= HOT or (r, c) in seen:
                continue
            region, stack = [], [(r, c)]
            seen.add((r, c))
            while stack:
                y, x = stack.pop()
                region.append((y, x))
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= ny < rows and 0 <= nx < cols and (ny, nx) not in seen and grid[ny][nx] > HOT:
                        seen.add((ny, nx))
                        stack.append((ny, nx))
            py, px = max(region, key=lambda yx: grid[yx[0]][yx[1]])
            if px in (0, cols - 1):
                continue      # clipped by the image edge: the peak is not the body's centre
            left, mid, right = grid[py][px - 1], grid[py][px], grid[py][px + 1]
            den = left - 2 * mid + right
            col = px + (0.5 * (left - right) / den if den < 0 else 0.0)   # sub-cell parabola fit
            if best is None or mid > best[0]:
                best = (mid, col)
    return best


def column_bearing(col, width=THERMAL_W):
    """Bearing (radians, + left) of a thermal column centre: column 0 is the left edge, as sim draws it."""
    return (0.5 - (col + 0.5) / width) * FOV_H


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def intersect(p, a, q, b):
    """Point where ray p->a meets ray q->b (both forward), or None."""
    d1, d2 = (math.cos(a), math.sin(a)), (math.cos(b), math.sin(b))
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < math.sin(MIN_ANGLE):
        return None
    wx, wy = q[0] - p[0], q[1] - p[1]
    s = (wx * d2[1] - wy * d2[0]) / den
    t = (wx * d1[1] - wy * d1[0]) / den
    if s <= 0 or t <= 0 or s > 8 or t > 8:
        return None
    return (p[0] + s * d1[0], p[1] + s * d1[1])


class Casualties:
    def __init__(self, ask=None, clock=time.monotonic, vision_on=None):
        self.ask = ask if ask is not None else gem_ask
        self.vision_on = vision_on if vision_on is not None else (lambda: ask is not None or gem_on())
        self.clock = clock
        self.sound = deque(maxlen=AVERAGE)      # (scene bearing, level)
        self.thermal_rays = deque(maxlen=100)   # (xy, scene bearing)
        self.sound_rays = deque(maxlen=100)     # (xy, scene bearing), only loud, averaged samples
        self.crossings = deque(maxlen=300)      # triangulated points
        self.points = deque(maxlen=200)         # thermal + LiDAR range points
        self.found = []                         # [{"pos", "z", "thermal", "sound", "vision"}]
        self.last_vision = -math.inf
        self.vision_stand_in = False            # True once vision was skipped (Gemini off): flag it
        self.suggested = False                  # the last frame had a thermal or sound clue
        self.pending = False                    # a vision call is in flight
        self.dirty = False                      # map/casualties changed since it was last published

    def on_sensors(self, data):
        """Fuse one sensors/scout frame's thermal and sound; return True if map/casualties changed."""
        pos, yaw = data["pose"]["pos"], data["pose"].get("yaw", 0.0)
        xy = tuple(pos[:2])
        thermal_score = sound_score = 0.0

        hot = thermal_region(data["thermal"]) if data.get("thermal") else None
        if hot:
            peak, col = hot
            thermal_score = min(1.0, (peak - BACKGROUND) / (0.8 - BACKGROUND))
            bearing = wrap(yaw + column_bearing(col, len(data["thermal"][0])))
            self._cross((xy, bearing), list(self.thermal_rays) + list(self.sound_rays))
            self.thermal_rays.append((xy, bearing))
            r = _range_at(data.get("lidar"), bearing)
            if r is not None and r < THERMAL_MAX_RANGE:
                self.points.append((xy[0] + r * math.cos(bearing), xy[1] + r * math.sin(bearing)))

        ac = data.get("acoustic")
        if ac:
            self.sound.append((wrap(yaw + math.radians(ac["bearing"])), ac["level"]))
            level = statistics.fmean(v for _, v in self.sound)
            if level > SOUND_FLOOR and len(self.sound) == AVERAGE:
                sound_score = min(1.0, level / SOUND_FULL)
                if level >= SOUND_FULL:      # faint sound bearings are too noisy to triangulate
                    bearing = math.atan2(sum(math.sin(b) for b, _ in self.sound),
                                         sum(math.cos(b) for b, _ in self.sound))
                    self._cross((xy, bearing), list(self.thermal_rays))
                    self.sound_rays.append((xy, bearing))

        self.suggested = bool(thermal_score or sound_score)
        estimate = self._estimate()
        if estimate is None:
            return False
        return self._update(estimate, pos[2], thermal_score, sound_score)

    def vision_due(self, data):
        """The frame's base64 JPEG if a vision call is due now (a clue suggests someone, 1 s apart), else None.

        With Gemini off no call is made: vision is marked as a stand-in and None returned.
        """
        camera = data.get("camera")
        if camera is None or not self.suggested or self.pending or self.clock() - self.last_vision < VISION_PERIOD:
            return None
        if not self.vision_on():
            if not self.vision_stand_in and gem is not None:
                gem.mark_stand_in("vision")     # the console badge shows vision ran as a stand-in
            self.vision_stand_in = True
            return None
        self.last_vision = self.clock()
        self.pending = True
        return camera["b64"] if isinstance(camera, dict) else camera

    def on_vision(self, answer):
        """Apply a vision answer (JSON text, or None when the call fell back); return True if changed."""
        self.pending = False
        if answer is None:
            self.vision_stand_in = True
            return False
        try:
            out = json.loads(answer.strip().removeprefix("```json").removesuffix("```"))
        except (ValueError, AttributeError):
            return False
        score = 0.0
        if isinstance(out, dict) and out.get("person"):
            score = {"lying": 1.0, "sitting": 1.0, "standing": 0.6}.get(out.get("posture"), 0.5)
        if not self.found or score <= self.found[-1]["vision"]:
            return False
        self.found[-1]["vision"] = score
        return True

    def step(self, data):
        """on_sensors, then a blocking vision call if one is due (tests and offline runs)."""
        changed = self.on_sensors(data)
        b64 = self.vision_due(data)
        if b64 is not None:
            answer = self.ask(PROMPT, b64)
            changed = self.on_vision(answer) or changed
        return changed

    def _cross(self, ray, others):
        """Triangulate a new ray against stored rays from Scout poses at least BASELINE away."""
        p, a = ray
        for q, b in others:
            if math.dist(p, q) >= BASELINE:
                x = intersect(p, a, q, b)
                if x:
                    self.crossings.append(x)

    def _estimate(self):
        """Median triangulated point, else median thermal point, else None."""
        pts = list(self.crossings) or list(self.points)
        if not pts:
            return None
        return (statistics.median(x for x, _ in pts), statistics.median(y for _, y in pts))

    def _update(self, xy, z, thermal, sound):
        for c in self.found:
            if math.dist(c["pos"], xy) < MERGE:
                before = self._entry(c, 0)
                c["pos"] = xy
                c["thermal"] = max(c["thermal"], thermal)
                c["sound"] = max(c["sound"], sound)
                return self._entry(c, 0) != before
        if thermal == 0:
            return False      # sound alone gives a bearing, not a place
        self.found.append({"pos": xy, "z": z, "thermal": thermal, "sound": sound, "vision": 0.0})
        return True

    @staticmethod
    def _entry(c, n):
        clues = [name for name, key in (("pose", "vision"), ("thermal", "thermal"), ("sound", "sound")) if c[key] > 0]
        confidence = 0.4 * c["thermal"] + 0.3 * c["sound"] + 0.3 * c["vision"]
        return {"id": f"c{n + 1}", "pos": [round(c["pos"][0], 2), round(c["pos"][1], 2), round(c["z"], 3)],
                "confidence": round(confidence, 2), "clues": clues, "vitals": dict(VITALS)}

    def message(self):
        """The map/casualties list, exactly the contract shape."""
        return [self._entry(c, n) for n, c in enumerate(self.found)]


def _range_at(lidar, bearing):
    """Shortest LiDAR range within one ray of `bearing` (ray k at 2*pi*k/n from scene +x)."""
    if not lidar:
        return None
    n = len(lidar)
    k = round((bearing % (2 * math.pi)) / (2 * math.pi) * n) % n
    return min(lidar[(k + d) % n] for d in (-1, 0, 1))


def gem_on():
    """True when coord/gem.py exists and GEMINI_MODE is not off."""
    return gem is not None and gem.MODE != "off"


def gem_ask(prompt, b64):
    """One vision call through coord/gem.py; None when Gemini is off or not installed (a stand-in)."""
    if gem is None:
        return None
    try:
        contents = [{"role": "user", "parts": [{"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                                               {"text": prompt}]}]
        return gem.ask("fast_subagent", contents, thinking="low", feature="vision")
    except gem.GeminiOff:
        gem.mark_stand_in("vision")
        return None
