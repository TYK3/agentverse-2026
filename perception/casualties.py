"""Casualty detection: thermal, sound and (optionally) vision fused into map/casualties, no faces (T10).

Thermal: the strongest connected region of the 16x12 grid above 0.6 gives a bearing (camera field of
view 60 degrees across), and the LiDAR range along that bearing gives a point.
Sound: the acoustic bearing, averaged over the last 5 samples (circular mean, in the scene frame).
Fusion: rays (Scout position, scene bearing) from poses at least 1 m apart are intersected; the
median of the intersections is the position, or the median thermal point while there is no pair.
Confidence = 0.4*thermal + 0.3*sound + 0.3*vision, each clue scored 0..1.
Provisional vs supported (CASUALTY-FUSE, #166): a thermal point is only the first LiDAR surface along
the thermal bearing, which may be debris in front of the casualty. Until two rays cross, the casualty
is a provisional track: there is at most one, and it follows the median thermal point wherever it
drifts (one hypothesis moving, never a new casualty per drift). The first crossing turns that same
track (same id, so the planner's queue entry moves with it) into a supported one at the triangulated
point. A later supported estimate beyond MERGE from every supported track is a further casualty, as
before. Confidence is not capped: Z3's thermal + sound + camera agreement still reaches >= 0.8 offline.
Vision: the camera frame goes to gemini-3.8-flash through coord/gem.py, at most once a second and
only when thermal or sound already suggests someone. With GEMINI_MODE=off (or no coord/gem.py) it is
skipped and marked as a stand-in. The frame is dropped right after the call: never stored or sent.
Offline camera check (Z3): with Gemini off, the Scout's own camera frame is checked locally instead,
also at most once a second and only while thermal sees someone: the largest warm-coloured blob (the
sim's casualty marker colour; a real robot would run a local person detector here) scores as vision
only if it is in the same direction as the thermal peak (within AGREE_DEG) and big enough; lying
(wider than tall) scores 1.0, otherwise 0.7. A red object with no heat behind it (the Responder's
first aid kit) does not count. So thermal + sound + camera agreeing reach >= 0.8 with Gemini off.
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
CAM_FOVY = math.radians(60.0)   # sim/scenes/backup.xml scout_cam; horizontal FOV follows the frame's aspect
AGREE_DEG = 12.0      # camera blob and thermal peak must point within this many degrees of each other
MIN_BLOB = 0.002      # blob area as a fraction of the frame, below this it is noise
CAM_STEP = 4          # check every 4th pixel each way (80x60 for a 320x240 frame)
PROMPT = (
    "Is there a person-shaped figure (or a red capsule/cylinder representing a trapped casualty "
    "in this physics simulation) lying or sitting in this image? Answer JSON only: "
    '{"person": bool, "bbox": [x,y,w,h], "posture": "lying|sitting|standing|unknown"}. '
    "Do not describe faces."
)

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
        self.found = []                         # [{"pos", "z", "thermal", "sound", "vision", "supported"}]
        self.last_vision = -math.inf
        self.vision_stand_in = False            # True once vision was skipped (Gemini off): flag it
        self.suggested = False                  # the last frame had a thermal or sound clue
        self.pending = False                    # a vision call is in flight
        self.dirty = False                      # map/casualties changed since it was last published
        self.thermal_rel = None                 # bearing (radians, + left) of this frame's thermal peak
        self.last_local = -math.inf             # clock() of the last offline camera check

    def on_sensors(self, data):
        """Fuse one sensors/scout frame's thermal and sound; return True if map/casualties changed."""
        pos, yaw = data["pose"]["pos"], data["pose"].get("yaw", 0.0)
        xy = tuple(pos[:2])
        thermal_score = sound_score = 0.0

        hot = thermal_region(data["thermal"]) if data.get("thermal") else None
        self.thermal_rel = None
        if hot:
            peak, col = hot
            thermal_score = min(1.0, (peak - BACKGROUND) / (0.8 - BACKGROUND))
            self.thermal_rel = column_bearing(col, len(data["thermal"][0]))
            bearing = wrap(yaw + self.thermal_rel)
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
        changed = self._update(estimate, pos[2], thermal_score, sound_score, supported=bool(self.crossings))
        return self._local_vision(data, estimate) or changed

    def _local_vision(self, data, estimate):
        """Offline camera check (Z3), only while Gemini vision is off; True if a casualty's score rose."""
        camera = data.get("camera")
        vision_on = self.vision_on() if callable(self.vision_on) else bool(self.vision_on)
        if (vision_on or camera is None or self.thermal_rel is None
                or self.clock() - self.last_local < VISION_PERIOD):
            return False
        self.last_local = self.clock()
        score = local_person(camera["b64"] if isinstance(camera, dict) else camera, self.thermal_rel)
        if not score:
            return False
        c = min(self.found, key=lambda f: math.dist(f["pos"], estimate), default=None)
        if c is None or math.dist(c["pos"], estimate) >= MERGE or score <= c["vision"]:
            return False
        c["vision"] = score
        return True

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

    def _update(self, xy, z, thermal, sound, supported=True):
        """Fold one estimate into the tracks; True if map/casualties changed.

        Supported (triangulated) estimates merge into the supported track within MERGE, else take over
        the provisional track, else start a new one. Unsupported estimates only ever move the single
        provisional track: the median thermal point drifting is one hypothesis moving, not a new casualty.
        """
        provisional = next((c for c in self.found if not c.get("supported", True)), None)
        target = None
        if supported:
            target = next((c for c in self.found if c.get("supported", True) and math.dist(c["pos"], xy) < MERGE),
                          None) or provisional
        elif provisional is not None:
            target = provisional
        elif any(math.dist(c["pos"], xy) < MERGE for c in self.found):
            return False      # a stray thermal point beside a supported casualty: nothing new
        if target is not None:
            before = self._entry(target, 0)
            target["pos"] = xy
            target["z"] = z
            target["thermal"] = max(target["thermal"], thermal)
            target["sound"] = max(target["sound"], sound)
            target["supported"] = target.get("supported", True) or supported
            return self._entry(target, 0) != before
        if thermal == 0:
            return False      # sound alone gives a bearing, not a place
        self.found.append({"pos": xy, "z": z, "thermal": thermal, "sound": sound, "vision": 0.0,
                           "supported": supported})
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


def local_person(b64, thermal_rel):
    """Offline camera score: 1.0 lying / 0.7 upright for a warm-coloured blob in the thermal direction, else 0.

    The frame is decoded, checked and dropped here; nothing is stored. Needs Pillow; without it, 0.
    """
    try:
        import base64
        import io

        from PIL import Image
        img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    except Exception:  # noqa: BLE001 -- no Pillow, or a bad frame: no camera clue
        return 0.0
    width, height = img.size
    px = img.load()
    cols, rows = range(0, width, CAM_STEP), range(0, height, CAM_STEP)
    warm = set()
    for j, y in enumerate(rows):
        for i, x in enumerate(cols):
            r, g, b = px[x, y]
            if r > 90 and r > 1.5 * g and r > 1.5 * b:
                warm.add((i, j))
    best, seen = None, set()
    for start in warm:
        if start in seen:
            continue
        blob, stack = [], [start]
        seen.add(start)
        while stack:
            i, j = stack.pop()
            blob.append((i, j))
            for n in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if n in warm and n not in seen:
                    seen.add(n)
                    stack.append(n)
        if best is None or len(blob) > len(best):
            best = blob
    if not best or len(best) < MIN_BLOB * len(cols) * len(rows):
        return 0.0
    xs, ys = [i for i, _ in best], [j for _, j in best]
    blob_w, blob_h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    # Agreement: the blob covers the thermal direction (within AGREE_DEG). Its centre alone is not
    # used: close up the body fills the frame and is cut off at the edge, which moves the centre.
    fov_h = 2 * math.atan(math.tan(CAM_FOVY / 2) * width / height)
    col = (0.5 - thermal_rel / fov_h) * len(cols)              # thermal direction as a column (+ left)
    margin = math.radians(AGREE_DEG) / fov_h * len(cols)
    if not (min(xs) - margin <= col <= max(xs) + 1 + margin):
        return 0.0
    return 1.0 if blob_w >= 1.3 * blob_h else 0.7


def gem_on():
    """True when coord/gem.py exists and GEMINI_MODE is not off."""
    return gem is not None and gem.MODE != "off"


def gem_ask(prompt, b64):
    """One vision call through coord/gem.py; None when Gemini is off or not installed (a stand-in)."""
    if gem is None:
        return None
    try:
        contents = [{"type": "image", "mime_type": "image/jpeg", "data": b64},
                    {"type": "text", "text": prompt}]
        return gem.ask("fast_subagent", contents, thinking="low", feature="vision")
    except gem.GeminiOff:
        gem.mark_stand_in("vision")
        return None
