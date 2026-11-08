"""L5 checks: keep-out zones from sensed debris motion, lifted only by fresh quiet re-scans."""

import pytest

from perception.grid import Grid
from perception.hazards import Hazards
from perception.motion import DEPTH_CARVE, EXCLUDE, QUIET_FRAMES, MotionWatch

EYE = [0.0, 0.0, 0.3]
WALL = [[1.0, -0.2 + 0.05 * k + 0.025, 0.3] for k in range(8)]         # a face 1 m ahead, 8 voxels wide
BACK = [[2.0, p[1], 0.3] for p in WALL]                                 # what is behind it once it moves


def frame(w, t, ends, eye=EYE):
    w.t = t
    w.obs = {}
    for e in ends:
        w.ray(eye, e)
    for key, hit in w.obs.items():
        (w._hit if hit else w._pass)(key)
    w.seen = {v for v, _ in w.obs}
    w._frame()


def test_a_face_that_moves_away_opens_a_zone_and_only_quiet_rescans_lift_it():
    w = MotionWatch()
    for t in range(6):
        frame(w, t * 0.1, WALL)
    assert w.zones == []
    for t in range(6, 9):                                              # the face is gone: rays reach the back
        frame(w, t * 0.1, BACK)
    assert len(w.zones) == 1 and w.zones[0].kinds == {"vanished"}
    out = w.keep_out()
    assert (20, 0) in out and (20 + int(EXCLUDE / 0.05), 0) in out and (20 + int(EXCLUDE / 0.05) + 1, 0) not in out
    assert "precaution from observed motion" in out[(20, 0)]
    w.t = 100.0
    w._frame()                                                         # time alone, nothing re-measured
    assert len(w.zones) == 1
    for t in range(QUIET_FRAMES):
        frame(w, 101 + t * 0.1, BACK)
    assert w.zones == [] and len(w.lifted) == 1


def test_motion_during_rescans_restarts_the_quiet_count():
    w = MotionWatch()
    for t in range(6):
        frame(w, t * 0.1, WALL)
    for t in range(6, 9):
        frame(w, t * 0.1, BACK)
    nearer = [[0.8, p[1], 0.3] for p in WALL]                          # debris slides in nearer
    for t in range(9, 12):
        frame(w, t * 0.1, nearer)
    zone = w.zones[0]
    assert len(w.zones) == 1 and "appeared" in zone.kinds and zone.last == pytest.approx(1.0)
    assert zone.quiet == 1                                             # frame 11 was the first quiet one
    for t in range(12, 12 + QUIET_FRAMES - 2):
        frame(w, t * 0.1, nearer)
    assert w.zones == [zone]                                           # one quiet frame short
    frame(w, 2.0, nearer)
    assert w.zones == []


def floor_frame(w, t, z):
    """One sensors/scout frame of a still floor seen by the depth camera, more points than DEPTH_CARVE (so
    only some are walked as rays), each return at height `z`: the real sim reports floor hits at 0.000
    or -0.001 m, either side of the voxel boundary at 0."""
    cam = [0.0, 0.0, 0.105]
    pts = [[0.3 + 0.02 * i, -0.3 + 0.02 * j, z] for i in range(40) for j in range(30)]
    assert len(pts) > DEPTH_CARVE
    w.add_sensors({"t": t, "pose": {"pos": [-0.1, 0.0, 0.075], "yaw": 0.0}, "points": pts, "points_from": cam})


def test_floor_returns_on_the_voxel_boundary_are_not_motion():
    """ref #144 seed 23: walked and unwalked depth points must bin a return the same way (INTO past it), or a
    still floor at z = 0.000 vs -0.001 m flips voxels in the bottom layer and opens zones that never lift."""
    w = MotionWatch()
    for k in range(40):
        floor_frame(w, k * 0.5, 0.0 if (k // 6) % 2 == 0 else -0.001)
    assert w.zones == [] and w.lifted == []


def cargo(x):
    """Rays at the face of the Responder's deck cargo (0.12-0.23 m up) when it is at x, else the far wall."""
    return [[x, -0.1 + 0.05 * k + 0.025, 0.3] for k in range(4)]


def test_the_responder_and_its_cargo_are_not_debris():
    """ref #144 seeds 22/23: the Scout's camera sees the supplies on the Responder's deck (they are not robot
    geoms). Driving past, they 'land' and 'move away', which opened keep-out zones on the Responder's own
    route and revoked it. Motion within ROBOT_R of where responder/pose put it in the last ROBOT_S is not debris."""
    w = MotionWatch()
    for t in range(6):
        frame(w, t * 0.1, BACK[:4])                                    # a free view to the back wall
    for k, t in enumerate(range(6, 20)):
        x = 1.0 + 0.02 * k                                             # the Responder drives across the view
        w.on_responder({"t": t * 0.1, "pos": [x, 0.0, 0.05]})
        frame(w, t * 0.1, cargo(x) if k < 8 else BACK[:4])             # then it is gone again
    assert w.zones == [] and w.lifted == [], "no zone may open, not even one that lifts later"


def test_debris_away_from_the_responder_still_opens_a_zone():
    w = MotionWatch()
    w.on_responder({"t": 0.0, "pos": [-1.0, -1.0, 0.05]})              # parked well away from the wall
    for t in range(6):
        frame(w, t * 0.1, WALL)
    for t in range(6, 9):
        w.on_responder({"t": t * 0.1, "pos": [-1.0, -1.0, 0.05]})
        frame(w, t * 0.1, BACK)
    assert len(w.zones) == 1


def test_a_new_viewpoint_is_not_motion():
    """From another place a surface corner can look free: that is aliasing, so states are per viewpoint."""
    w = MotionWatch()
    for t in range(6):
        frame(w, t * 0.1, WALL)
    for t in range(6, 12):
        frame(w, t * 0.1, BACK, eye=[0.0, 0.5, 0.3])                   # 0.5 m to the side
    assert w.zones == []


def test_hazards_publish_the_zone_as_exclusion_and_collapsed_wins():
    g = Grid()
    h = Hazards(g)
    for t in range(6):
        frame(h.motion, t * 0.1, WALL)
    for t in range(6, 9):
        frame(h.motion, t * 0.1, BACK)
    h.collapsed[(21, 0)] = "scan diff: debris landed here"
    msg = h.update(1.0)
    by = {tuple(m["cell"][:2]): m for m in msg}
    assert by[(20, 0)]["exclusion"] is True and by[(20, 0)]["status"] == "at_risk"
    assert by[(20, 0)]["why"].startswith("exclusion zone: debris moved away 0.28-0.28 m up")
    assert by[(21, 0)]["status"] == "collapsed" and by[(21, 0)]["exclusion"] is True
    assert all("exclusion" not in m for m in msg if tuple(m["cell"][:2]) not in h.excluded)


# ---- the backup scene (needs mujoco) -------------------------------------------

@pytest.fixture(scope="module")
def explored():
    pytest.importorskip("mujoco")
    from perception.tests.closed_loop import Loop
    loop = Loop()
    loop.run(90)
    return loop


def test_no_zone_while_exploring_a_still_scene(explored):
    assert explored.hazards.motion.zones == [] and explored.hazards.motion.lifted == []


def test_sliding_slab_is_kept_out_then_released_after_quiet_rescans(explored):
    """The test world slides b10 0.15 m down its lean over 3 s while the Scout watches from room 2."""
    from perception.tests.closed_loop import footprint
    from planner.route import find_route
    loop = explored
    loop.watch(0.25, -0.5, 0.0, 20)                                    # settle the view first
    assert loop.hazards.motion.zones == []
    adr = loop.m.joint(loop.m.body("b10").jntadr[0]).qposadr[0]

    def slide(m, d):
        d.qpos[adr] -= 0.005
        d.qpos[adr + 2] -= 0.002

    loop.watch(0.25, -0.5, 0.0, 30, move=slide)
    zones = loop.hazards.motion.zones
    assert zones and max(z.heights()[1] for z in zones) > 0.3          # seen above the LiDAR plane
    msg = loop.hazards.update(loop.t)
    keep_out = {tuple(m["cell"][:2]) for m in msg if m.get("exclusion")}
    assert footprint(loop.m, loop.d, "b10") & keep_out
    snapshot = loop.grid.snapshot(loop.t)
    cells = sorted(keep_out)
    free = [c["cell"] for c in snapshot["cells"] if not c["occupied"] and c["state"] == "seen"
            and tuple(c["cell"][:2]) in keep_out]
    if free:                                                           # a route into the zone is refused
        assert find_route(snapshot, msg, free[0], free[-1])["status"] == "no_verified_route"
    loop.watch(0.25, -0.5, 0.0, 60)                                    # 6 s still: quiet re-scans
    assert loop.hazards.motion.zones == [] and cells
