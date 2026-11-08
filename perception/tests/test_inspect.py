"""G2 checks: an ER point becomes a Scout inspection goal only where the Scout's own depth points
ground it, through the real scout_cam geometry; ungrounded points are rejected and logged."""

import json
import math
from types import SimpleNamespace

import mujoco
import numpy as np
import pytest

from perception import inspect as I
from sim.world import World


def er(*pts):
    """An ER answer pointing at pixels (u, v)."""
    return json.dumps([{"point": [round(v / I.H * 1000), round(u / I.W * 1000)], "label": f"gap {k}"}
                       for k, (u, v) in enumerate(pts)])


@pytest.fixture(scope="module")
def world():
    w = World(render=False)
    w._set_pose((0.15, 0.0), math.radians(20))    # in room 2 by the west wall, looking east toward b8
    mujoco.mj_forward(w.m, w.d)
    return w


def pose_of(w):
    return w.sensors_message(camera=False)["pose"]


def mj_ray_dir(w, u, v):
    """Pixel ray from MuJoCo's own scout_cam frame (camera looks along -z, x right, y up)."""
    cam = w.m.camera("scout_cam").id
    R = w.d.cam_xmat[cam].reshape(3, 3)
    d = R @ np.array([(u - I.W / 2) / I.F_PX, -(v - I.H / 2) / I.F_PX, -1.0])
    return d / np.linalg.norm(d)


def depth_points(w, step=8):
    """A stand-in depth camera on scout_cam (Y9 not wired in the sim): hit points over a pixel grid."""
    cam = w.m.camera("scout_cam").id
    origin = w.d.cam_xpos[cam].copy()
    groups = np.array([1, 1, 1, 0, 1, 1], dtype=np.uint8)     # leave out robot geoms (group 3)
    geomid, pts = np.zeros(1, dtype=np.int32), []
    for v in range(0, I.H, step):
        for u in range(0, I.W, step):
            d = mj_ray_dir(w, u, v)
            dist = mujoco.mj_ray(w.m, w.d, origin, d, groups, 1, -1, geomid)
            if 0 <= dist <= I.MAX_RANGE_M:
                pts.append([float(x) for x in origin + d * dist])
    return pts


# ---- geometry against MuJoCo ----------------------------------------------------------------------

def test_camera_model_matches_mujoco(world):
    pose = pose_of(world)
    cam = world.m.camera("scout_cam").id
    assert np.allclose(I.camera_origin(pose), world.d.cam_xpos[cam], atol=0.005)
    assert math.isclose(math.degrees(2 * math.atan((I.H / 2) / I.F_PX)), world.m.cam_fovy[cam], abs_tol=0.01)
    for u, v in ((I.W / 2, I.H / 2), (0, 0), (I.W - 1, I.H - 1), (40, 200)):
        assert np.allclose(I.pixel_ray(pose, u, v), mj_ray_dir(world, u, v), atol=1e-3), (u, v)


# ---- grounding in the real scene ------------------------------------------------------------------

def test_er_point_on_a_surface_becomes_a_goal_at_the_measured_depth(world):
    pose, ins = pose_of(world), I.Inspector()
    ins.keep_points({"points": depth_points(world)}, now=0)
    u, v = 160, 120
    out = ins.goals(pose, er((u, v)), receipt="gem-" + "a" * 32, model="gemini-robotics-er-2-preview", now=3)
    topics = [t for t, _ in out]
    assert topics == ["scout/goto", "log/decision"], out
    goto, log = out[0][1], out[1][1]
    cam = world.m.camera("scout_cam").id
    true = mujoco.mj_ray(world.m, world.d, world.d.cam_xpos[cam], mj_ray_dir(world, u, v),
                         np.array([1, 1, 1, 0, 1, 1], dtype=np.uint8), 1, -1, np.zeros(1, dtype=np.int32))
    measured = float(log["reason"].split("depth at ")[1].split(" m")[0])
    assert abs(measured - true) < 0.1, (measured, true)
    gx, gy, gz = goto["target"]
    origin = np.array(I.camera_origin(pose))
    assert math.isclose(math.dist((gx, gy), origin[:2]), max(0, measured - I.STANDOFF_M) *
                        math.hypot(*I.pixel_ray(pose, u, v)[:2]), abs_tol=0.02)
    assert gz == I.SCOUT_Z and "gem-" + "a" * 32 in goto["reason"]
    assert log["outcome"] == "inspect" and log["model"] == "gemini-robotics-er-2-preview" and log["t"] == 3


def test_er_point_without_a_depth_return_is_rejected(world):
    pose, ins = pose_of(world), I.Inspector()
    pts = depth_points(world)
    ray = I.pixel_ray(pose, 300, 20)                     # top-right corner: drop every point near that ray
    o = I.camera_origin(pose)
    keep = [p for p in pts if I.ground(o, ray, [p]) is None]
    assert len(keep) < len(pts), "the stand-in depth camera saw something along that ray"
    ins.keep_points({"points": keep}, now=0)
    out = ins.goals(pose, er((300, 20), (160, 120)), now=1)
    outcomes = [d["outcome"] for t, d in out if t == "log/decision"]
    assert outcomes == ["rejected_ungrounded", "inspect"]
    assert sum(t == "scout/goto" for t, _ in out) == 1


def test_a_surface_inside_the_standoff_is_inspected_from_where_the_scout_is():
    w = World(render=False)
    w._set_pose((0.6, 0.0), math.radians(20))       # 0.5 m from b8
    mujoco.mj_forward(w.m, w.d)
    ins = I.Inspector()
    ins.keep_points({"points": depth_points(w)}, now=0)
    out = ins.goals(pose_of(w), er((160, 120)))
    assert [d["outcome"] for _, d in out] == ["in_view"]


def test_same_place_is_not_sent_twice_and_bad_answers_give_nothing(world):
    pose, ins = pose_of(world), I.Inspector()
    ins.keep_points({"points": depth_points(world)}, now=0)
    assert [t for t, _ in ins.goals(pose, er((160, 120)))] == ["scout/goto", "log/decision"]
    again = ins.goals(pose, er((162, 121)))
    assert [d["outcome"] for _, d in again] == ["skipped"]
    for bad in ("not json", "[]", '[{"point": [2000, 5]}]', '[{"label": "x"}]', '{"point": [1, 2]}'):
        assert ins.goals(pose, bad) == [], bad


# ---- when ER is asked -------------------------------------------------------------------------------

def test_er_only_with_a_camera_fresh_depth_and_the_rate_limit():
    ins = I.Inspector()
    frame = {"camera": {"format": "jpeg", "b64": "x"}, "pose": {"pos": [0, 0, 0.075], "yaw": 0}}
    assert not ins.due(frame, 0), "no depth points yet"
    ins.keep_points({"points": [[1, 0, 0.1]]}, now=0)
    assert ins.due(frame, 0.5)
    assert not ins.due(frame, 0.5 + I.POINTS_MAX_AGE_S + 0.1), "depth too old to ground this frame"
    ins.keep_points({"points": [[1, 0, 0.1]]}, now=5)
    ins.last_ask = 5
    assert not ins.due(frame, 5.5) and not ins.due({**frame, "camera": None}, 30)
    ins.keep_points({"points": [[1, 0, 0.1]]}, now=5 + I.ER_EVERY_S)
    assert ins.due(frame, 5 + I.ER_EVERY_S)


class FakeGem:
    def __init__(self, answer):
        self.answer, self.calls, self.stand_ins = answer, [], set()
        self.MODEL_IDS = {"embodied_reasoning": "gemini-robotics-er-2-preview"}

    def ask_with_receipt(self, key, contents, thinking="medium", feature="?", **kw):
        self.calls.append((key, feature, contents))
        if isinstance(self.answer, Exception):
            raise self.answer
        return SimpleNamespace(text=self.answer, receipt={"id": "gem-" + "b" * 32})

    def mark_stand_in(self, feature):
        self.stand_ins.add(feature)


def test_ask_er_goes_through_gem_with_the_frame_and_a_receipt():
    gem = FakeGem("[]")
    assert I.ask_er(gem, "QUJD") == ("[]", "gem-" + "b" * 32, "gemini-robotics-er-2-preview")
    key, feature, contents = gem.calls[0]
    assert key == "embodied_reasoning" and feature == "spatial_inspection"
    assert contents[0]["parts"][0]["inline_data"] == {"mime_type": "image/jpeg", "data": "QUJD"}

    class GeminiOff(Exception):
        pass
    off = FakeGem(GeminiOff("spatial_inspection"))
    assert I.ask_er(off, "QUJD") == (None, None, None) and off.stand_ins == {"spatial_inspection"}


def test_goals_match_the_contract(world):
    messages = pytest.importorskip("coord.messages")
    ins = I.Inspector()
    ins.keep_points({"points": depth_points(world)}, now=0)
    for topic, data in ins.goals(pose_of(world), er((160, 120), (300, 5)), receipt="gem-" + "c" * 32, now=2):
        messages.validate_payload(topic, data)


def test_hub_wiring_sends_the_grounded_goal(world, monkeypatch):
    import asyncio

    import perception
    from coord import gem

    monkeypatch.setattr(gem, "MODE", "live")
    monkeypatch.setattr(gem, "ask_with_receipt", lambda *a, **k: SimpleNamespace(
        text=er((160, 120)), receipt={"id": "gem-" + "d" * 32}))

    class Bus:
        def __init__(self):
            self.subs, self.sent = {}, []

        def subscribe(self, topic, fn):
            self.subs.setdefault(topic, []).append(fn)

        async def publish(self, topic, data):
            self.sent.append((topic, data))

    async def go():
        bus = Bus()
        perception._inspect(bus, lambda: 1.0)
        frame = {**world.sensors_message(camera=False), "camera": {"format": "jpeg", "b64": "QUJD"},
                 "points": depth_points(world)}
        for fn in bus.subs["sensors/scout"]:
            fn(frame)
        await asyncio.sleep(0.2)
        return bus

    bus = asyncio.run(go())
    gotos = [d for t, d in bus.sent if t == "scout/goto"]
    assert len(gotos) == 1 and "gem-" + "d" * 32 in gotos[0]["reason"]
