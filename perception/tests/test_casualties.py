"""T10 checks: c1 found from thermal + sound on the T04 recording, thermal alone scores lower,
no casualty gives no entry, vision is gated and a flagged stand-in with Gemini off, frames are dropped."""

import itertools
import json
import math
import pathlib

import pytest

from perception.casualties import Casualties, column_bearing, thermal_region

RECORDING = pathlib.Path(__file__).resolve().parents[2] / "sim" / "recordings" / "scout_backup.jsonl"
C1 = (2.0, 1.0)       # casualty_c1 in sim/scenes/backup.xml


def frames():
    if not RECORDING.exists():
        pytest.skip("T04 recording sim/recordings/scout_backup.jsonl not present (#42)")
    return [json.loads(line)["data"] for line in RECORDING.read_text().splitlines() if line.strip()]


def run(c, data):
    for d in data:
        c.step(d)
    return c.message()


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_thermal_region_bearing():
    grid = [[0.1] * 16 for _ in range(12)]
    for r in range(5, 8):
        for col in (9, 10, 11):
            grid[r][col] = 0.7
    grid[6][10] = 0.9
    peak, col = thermal_region(grid)
    assert peak == 0.9 and col == pytest.approx(10.0)
    assert math.degrees(column_bearing(col)) == pytest.approx(-9.375)   # right of centre is negative
    edge = [[0.1] * 16 for _ in range(12)]
    edge[6][0] = 0.9
    assert thermal_region(edge) is None                                 # clipped at the edge: no bearing


def test_c1_found_from_two_clues():
    out = run(Casualties(vision_on=lambda: False), frames())
    assert len(out) == 1, out
    c1 = out[0]
    assert c1["id"] == "c1" and c1["confidence"] >= 0.7
    assert {"thermal", "sound"} <= set(c1["clues"])
    assert math.dist(c1["pos"][:2], C1) < 0.25, c1["pos"]
    assert c1["vitals"]["simulated"] is True
    assert set(c1) == {"id", "pos", "confidence", "clues", "vitals"}


def test_thermal_only_scores_lower():
    quiet = [{**d, "acoustic": {"bearing": 0.0, "level": 0.0}} for d in frames()]
    out = run(Casualties(vision_on=lambda: False), quiet)
    assert len(out) == 1 and out[0]["clues"] == ["thermal"]
    assert out[0]["confidence"] < 0.7


def test_no_casualty_no_entry():
    empty = [{**d, "thermal": [[0.1] * 16 for _ in range(12)], "acoustic": {"bearing": 30.0, "level": 0.02}}
             for d in frames()]
    assert run(Casualties(vision_on=lambda: False), empty) == []


def test_sound_alone_gives_no_entry():
    deaf = [{**d, "thermal": [[0.1] * 16 for _ in range(12)]} for d in frames()]
    assert run(Casualties(vision_on=lambda: False), deaf) == []


def test_vision_is_gated_and_frames_dropped():
    calls = []

    def ask(prompt, b64):
        calls.append(b64)
        assert "Do not describe faces" in prompt
        return '{"person": true, "bbox": [1, 2, 3, 4], "posture": "lying"}'

    clock = Clock()
    c = Casualties(ask=ask, clock=clock)
    data = frames()
    for d in data:
        clock.t = d["t"]
        c.step({**d, "camera": {"format": "jpeg", "b64": f"FRAME{d['t']}"}})
    assert calls, "vision was never asked"
    times = [float(b[5:]) for b in calls]
    assert all(b - a >= 1.0 - 1e-9 for a, b in itertools.pairwise(times))  # at most once a second
    first_clue = next(d["t"] for d in data if max(map(max, d["thermal"])) > 0.6 or d["acoustic"]["level"] > 0.1)
    assert times[0] >= first_clue                                           # only once a clue suggests someone
    c1 = c.message()[0]
    assert "pose" in c1["clues"] and c1["confidence"] >= 0.9
    assert "FRAME" not in json.dumps({k: v for k, v in vars(c).items() if k not in ("ask", "vision_on", "clock")},
                                     default=str)                           # no frame kept anywhere


def test_gemini_off_marks_vision_stand_in():
    asked = []
    c = Casualties(ask=lambda p, b: asked.append(b), vision_on=lambda: False)
    for d in frames()[:120]:
        c.step({**d, "camera": "FRAME"})
    assert asked == [] and c.vision_stand_in
    assert all("pose" not in e["clues"] for e in c.message())


# ---- Z3: offline camera check, so thermal + sound + camera reach >= 0.8 with Gemini off ----------

def _jpeg(blob_cols=None, w=320, h=240):
    """A grey frame with a red, person-coloured blob spanning `blob_cols` (x from, x to), base64 JPEG."""
    image = pytest.importorskip("PIL.Image")
    import base64
    import io

    img = image.new("RGB", (w, h), (120, 120, 120))
    if blob_cols:
        for x in range(*blob_cols):
            for y in range(110, 150):
                img.putpixel((x, y), (200, 60, 60))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_local_person_needs_agreement_with_thermal():
    from perception.casualties import local_person

    centre = _jpeg((120, 200))                         # a lying blob in the middle of the frame
    assert local_person(centre, 0.0) == 1.0            # thermal straight ahead: agrees
    assert local_person(centre, math.radians(35)) == 0.0   # thermal far left: disagrees
    assert local_person(_jpeg(None), 0.0) == 0.0       # nothing warm-coloured
    assert local_person(_jpeg((150, 160)), 0.0) == 0.7  # small and upright: not lying


def test_offline_camera_lifts_c1_to_0_8_with_gemini_off():
    """Real sim frames facing c1: thermal + sound + the offline camera check give >= 0.8 (Gemini off)."""
    pytest.importorskip("PIL.Image")
    sim_world = pytest.importorskip("sim.world")
    w = sim_world.World()
    if w.renderer is None:
        pytest.skip("no GL context for camera frames")
    t = itertools.count()
    c = Casualties(vision_on=lambda: False, clock=lambda: float(next(t)))
    for x, y in [(0.8, 0.6), (1.0, 0.65), (1.2, 0.7), (1.45, 0.7), (1.45, 0.7), (1.45, 0.7), (1.45, 0.7)]:
        w._set_pose((x, y), math.atan2(1.0 - y, 2.0 - x))
        w.tick(0.1)
        c.on_sensors(w.sensors_message())
    out = c.message()
    assert out and out[0]["confidence"] >= 0.8, out
    assert set(out[0]["clues"]) == {"pose", "thermal", "sound"}


def test_red_object_without_heat_is_not_a_casualty_clue():
    """The Responder's red first aid kit in view, with no thermal peak, scores no vision."""
    c = Casualties(vision_on=lambda: False)
    c.found.append({"pos": (0.0, 0.0), "z": 0.0, "thermal": 1.0, "sound": 0.0, "vision": 0.0})
    c.thermal_rel = None
    assert not c._local_vision({"camera": {"format": "jpeg", "b64": _jpeg((120, 200))}}, (0.0, 0.0))
    assert c.found[0]["vision"] == 0.0


def test_local_check_is_off_while_gemini_vision_is_on():
    c = Casualties(ask=lambda p, b: None, vision_on=lambda: True)
    c.found.append({"pos": (0.0, 0.0), "z": 0.0, "thermal": 1.0, "sound": 0.0, "vision": 0.0})
    c.thermal_rel = 0.0
    assert not c._local_vision({"camera": {"format": "jpeg", "b64": "x"}}, (0.0, 0.0))


def test_gem_ask_uses_interactions_content_blocks(monkeypatch):
    """gem_ask passes Interactions API image+text content blocks to coord/gem.py and marks stand-in when off."""
    from coord import gem
    from perception.casualties import PROMPT, gem_ask

    monkeypatch.setattr(gem, "MODE", "off")
    gem.stand_ins.discard("vision")
    assert gem_ask(PROMPT, "dGVzdA==") is None
    assert "vision" in gem.stand_ins

    recorded = []

    def fake_ask(model_key, contents, *, thinking="medium", feature="?", **kwargs):
        recorded.append((model_key, contents, thinking, feature))
        return '{"person": true, "bbox": [66, 90, 188, 52], "posture": "lying"}'

    monkeypatch.setattr(gem, "ask", fake_ask)
    ans = gem_ask(PROMPT, "dGVzdA==")
    assert json.loads(ans)["person"] is True
    assert recorded == [(
        "fast_subagent",
        [{"type": "image", "mime_type": "image/jpeg", "data": "dGVzdA=="},
         {"type": "text", "text": PROMPT}],
        "low",
        "vision",
    )]


def test_b1_sim_frames_casualty_detection_offline_and_vision_fixture():
    """Real B1 sim frames (levels.xml): thermal + sound + camera locate c1 on B1 with z < -0.5."""
    pytest.importorskip("PIL.Image")
    sim_levels = pytest.importorskip("sim.levels")
    w = sim_levels.LevelWorld(render=True)
    if w.renderer is None:
        pytest.skip("no GL context for camera frames")

    b1_poses = [(1.6, 1.1), (1.1, 1.3), (0.85, 1.5), (0.45, 1.1), (0.45, 1.0)]
    b1_frames = []
    for x, y in b1_poses:
        w._set_pose((x, y), math.atan2(1.9 - y, 0.45 - x))
        w._set_z(-0.6)
        w.tick(0.1)
        b1_frames.append(w.sensors_message(camera=True))

    t_off = itertools.count()
    c_off = Casualties(vision_on=lambda: False, clock=lambda: float(next(t_off)))
    for frame in b1_frames:
        c_off.on_sensors(frame)
    out_off = c_off.message()
    assert len(out_off) == 1, out_off
    assert out_off[0]["confidence"] >= 0.8
    assert set(out_off[0]["clues"]) == {"pose", "thermal", "sound"}
    assert math.dist(out_off[0]["pos"][:2], (0.45, 1.9)) < 0.25
    assert out_off[0]["pos"][2] == pytest.approx(-0.525)

    t_vis = itertools.count()
    c_vis = Casualties(
        ask=lambda p, b: '{"person": true, "bbox": [66, 90, 188, 52], "posture": "lying"}',
        clock=lambda: float(next(t_vis)),
    )
    for frame in b1_frames:
        c_vis.step(frame)
    out_vis = c_vis.message()
    assert len(out_vis) == 1 and out_vis[0]["confidence"] >= 0.9
    assert set(out_vis[0]["clues"]) == {"pose", "thermal", "sound"}

