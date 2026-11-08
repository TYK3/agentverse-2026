"""G2: Gemini ER points become depth-grounded inspection goals.

Gemini Robotics-ER looks at the Scout's camera frame and points at places a rescuer would want a
closer look at (a void that could hold a person, an overhang, a gap under a slab). A point on an
image is only a claim. Each one is turned into a ray through the Scout camera (level, looking along
the Scout's heading, fovy 60, 320 x 240), starting where the depth camera was for that frame
(`sensors/scout.points_from`; without it, `scout_cam`'s mount 0.1 m ahead and 0.03 m up)
and kept only if the Scout's own depth points (`sensors/scout.points`, Y9) land along that ray:
the first surface the depth camera measured there is where the goal is. A point with no depth
return along its ray is rejected and logged ("rejected_ungrounded"), never driven to.

A grounded point becomes a `scout/goto` inspection goal STANDOFF_M back along the ray at Scout
height, so the Scout looks into the void from in front of it; perception's Explorer gives a
scout/goto priority for its HOLD. ER is asked at most once every ER_EVERY_S, only when the frame
has a camera image and depth points fresh enough to ground against. Every call goes through
coord/gem.py with a receipt; the receipt id is in the goal's reason and the log/decision, so the
console can show why Gemini changed where the Scout went (G5).

ER never moves anything by itself: it only proposes, the depth points decide, and the goal goes
through the same Explorer and collision checks as every other Scout target.
"""

from __future__ import annotations

import json
import math
import re

W, H, FOVY_DEG = 320, 240, 60.0           # sim/scenes/backup.xml scout_cam, sim/sensors.py renderer size
CAM_OFFSET = (0.1, 0.0, 0.03)             # scout_cam in the Scout body frame (x forward, z up)
F_PX = (H / 2) / math.tan(math.radians(FOVY_DEG / 2))
ER_EVERY_S = 20.0                         # at most one ER call this often
POINTS_MAX_AGE_S = 1.0                    # depth points older than this cannot ground the camera frame
MAX_POINTS = 5                            # ER points used per call
RAY_TOL_RAD = math.radians(2.0)           # a depth point within this angle of the ray lies on it
RAY_TOL_MIN_M = 0.03
MIN_RANGE_M, MAX_RANGE_M = 0.15, 4.0
STANDOFF_M = 0.5                          # the goal sits this far back from the grounded point
SCOUT_Z = 0.075                           # goals are at Scout height (the LiDAR layer)
SAME_GOAL_M = 0.3                         # a goal this close to an earlier one is not repeated
MIN_MOVE_M = 0.15                         # a goal closer than this to the Scout: it is already looking from there
MODEL_KEY = "embodied_reasoning"
FEATURE = "spatial_inspection"

PROMPT = (
    "You are the camera of a small rescue robot inside a collapsed building. Point to at most "
    f"{MAX_POINTS} places a rescuer should inspect more closely: voids or gaps that could hold a "
    "trapped person, overhanging or leaning slabs, openings under rubble. Do not point at plain "
    'floor or intact walls. Answer JSON only: [{"point": [y, x], "label": "<two to four words>"}] '
    "with y and x normalised to 0-1000 (top-left is 0,0). Answer [] if nothing needs a closer look."
)


# ---- camera geometry --------------------------------------------------------------------------

def camera_origin(pose):
    """Scene-frame position of scout_cam for a sensors/scout pose {"pos": [x, y, z], "yaw": rad}."""
    x, y, z = pose["pos"]
    c, s = math.cos(pose["yaw"]), math.sin(pose["yaw"])
    ox, oy, oz = CAM_OFFSET
    return (x + c * ox - s * oy, y + s * ox + c * oy, z + oz)


def pixel_ray(pose, u, v):
    """Unit scene-frame direction through pixel (u, v) (u right, v down, from the top-left corner)."""
    fwd, right, up = 1.0, (u - W / 2) / F_PX, -(v - H / 2) / F_PX
    bx, by, bz = fwd, -right, up                    # body frame: x forward, y left, z up
    c, s = math.cos(pose["yaw"]), math.sin(pose["yaw"])
    d = (c * bx - s * by, s * bx + c * by, bz)
    n = math.sqrt(sum(k * k for k in d))
    return tuple(k / n for k in d)


def ground(origin, ray, points):
    """(distance along the ray, point) of the depth point best aligned with the ray, or None.

    Best aligned (smallest angle off the ray), not nearest: a ray grazing the floor passes within a
    few centimetres of floor points well before it reaches the surface it points at. A depth camera
    sees no further than the first surface along a pixel, so the best-aligned point is that surface."""
    best = None
    for p in points:
        rel = (p[0] - origin[0], p[1] - origin[1], p[2] - origin[2])
        t = rel[0] * ray[0] + rel[1] * ray[1] + rel[2] * ray[2]
        if not MIN_RANGE_M <= t <= MAX_RANGE_M:
            continue
        perp = math.sqrt(max(0.0, sum((rel[i] - t * ray[i]) ** 2 for i in range(3))))
        if perp > max(RAY_TOL_MIN_M, t * math.tan(RAY_TOL_RAD)):
            continue
        angle = math.atan2(perp, t)
        if best is None or angle < best[0]:
            best = (angle, t, tuple(p))
    return None if best is None else best[1:]


def parse_points(text):
    """ER's JSON answer -> [(u, v, label)] in pixels; malformed entries are dropped."""
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    try:
        items = json.loads(m.group(0)) if m else []
    except ValueError:
        return []
    out = []
    for it in items if isinstance(items, list) else []:
        try:
            yv, xv = (float(k) for k in it["point"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= yv <= 1000 and 0 <= xv <= 1000:
            label = " ".join(str(it.get("label") or "area").split()[:6])[:40]
            out.append((xv / 1000 * W, yv / 1000 * H, label))
    return out[:MAX_POINTS]


# ---- the inspector ----------------------------------------------------------------------------

class Inspector:
    """Pure core: `on_sensors(frame, now)` says whether ER is due; `goals(...)` grounds its answer."""

    def __init__(self):
        self.last_ask = float("-inf")
        self.points, self.points_t, self.points_from = [], None, None
        self.done = []              # scene (x, y) of goals already sent

    def keep_points(self, data, now):
        if data.get("points"):
            self.points, self.points_t = data["points"], now
            self.points_from = data.get("points_from")   # the camera position for these points (Y9)

    def due(self, data, now):
        """True when this frame should go to ER: a camera image, fresh depth points, rate limit."""
        cam = data.get("camera")
        fresh = self.points_t is not None and now - self.points_t <= POINTS_MAX_AGE_S
        return bool(cam) and fresh and data.get("pose") is not None and now - self.last_ask >= ER_EVERY_S

    def goals(self, pose, er_text, receipt=None, model="gemini-robotics-er", now=0.0):
        """-> list of (topic, data): a scout/goto and a log/decision per grounded point, a
        log/decision per rejected one."""
        out = []
        origin = tuple(self.points_from) if self.points_from else camera_origin(pose)
        rid = f" ({receipt})" if receipt else ""
        for u, v, label in parse_points(er_text):
            ray = pixel_ray(pose, u, v)
            hit = ground(origin, ray, self.points)
            seen = f"ER point '{label}' at pixel ({u:.0f}, {v:.0f})"
            if hit is None:
                out.append(_log(now, seen, model, "rejected_ungrounded",
                                f"no depth return along the ray within {MAX_RANGE_M} m: not grounded, not visited{rid}"))
                continue
            dist, p = hit
            back = max(0.0, dist - STANDOFF_M)
            gx, gy = origin[0] + ray[0] * back, origin[1] + ray[1] * back
            if math.hypot(gx - pose["pos"][0], gy - pose["pos"][1]) < MIN_MOVE_M:
                out.append(_log(now, seen, model, "in_view",
                                f"grounded at {dist:.2f} m, within the {STANDOFF_M} m standoff: inspected from here{rid}"))
                continue
            if any(math.hypot(gx - x, gy - y) < SAME_GOAL_M for x, y in self.done):
                out.append(_log(now, seen, model, "skipped", f"grounded at {dist:.2f} m but already inspected there{rid}"))
                continue
            self.done.append((gx, gy))
            reason = (f"G2 inspect '{label}': ER point grounded by depth at {dist:.2f} m, "
                      f"surface [{p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f}]{rid}")
            out.append(("scout/goto", {"target": [round(gx, 3), round(gy, 3), SCOUT_Z], "reason": reason}))
            out.append(_log(now, seen, model, "inspect", reason))
        return out


def _log(t, perception, model, outcome, reason):
    return ("log/decision", {"t": round(max(0.0, t), 2), "perception": perception, "model": model, "physics": "depth",
                             "outcome": outcome, "reason": reason[:300]})


def ask_er(gem, b64):
    """(text, receipt id, model) from one ER call through coord/gem.py; (None, None, None) when off,
    capped or failing (the stand-in is marked: no goals come from ER then)."""
    contents = [{"type": "image", "mime_type": "image/jpeg", "data": b64},
                {"type": "text", "text": PROMPT}]
    try:
        res = gem.ask_with_receipt(MODEL_KEY, contents, thinking="low", feature=FEATURE)
    except Exception as exc:  # noqa: BLE001 - off, cap, network, SDK: ER is optional, exploring goes on
        if type(exc).__name__ == "GeminiOff" and hasattr(gem, "mark_stand_in"):
            gem.mark_stand_in(FEATURE)
        return None, None, None
    return res.text, res.receipt.get("id"), getattr(gem, "MODEL_IDS", {}).get(MODEL_KEY, MODEL_KEY)
