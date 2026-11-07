# sim lane: the world and the robots

Spec: Function 1, the sensor half of Function 2, and the aftershock in Function 3 of `docs/aftershock.md`.

Owns: the MuJoCo scene of the tabletop collapsed building (the photo-to-scene builder with
`gemini-4-argon` and its self-critique loop, plus the hand-built backup scene), the Scout and Responder
robot models and the gripper, the simulated sensors (ray-cast LiDAR, camera, thermal, acoustic), the
scripted aftershock, and the physics check that runs a proposed route and reports unstable cells.

Ships first: the hand-built backup scene with both robots and a recorded sensor stream, so the other
lanes can build against it before the scene builder works.

Owner: see the owner table in `AGENTS.md`. Only this lane's agent edits files here; others ask on the board.

## Scout and sensors (T04)
- `sim.start(bus)` publishes `scene/loaded`, subscribes to `scout/goto` and publishes `sensors/scout`
  at 10 Hz in real time. The Scout is a mocap body driven at 0.3 m/s; it stops (`motion.state` =
  `blocked`) rather than drive into anything within 0.15 m.
- `sensors/scout` data: `t`, `pose` `{"pos":[x,y,z],"yaw":rad}`, `lidar` (360 ranges, ray k at k
  degrees counter-clockwise from scene +x, 6.0 = miss), `thermal` (12 rows x 16 columns, forward view,
  0.1 background, up to 0.9 on the casualty within 4 m and in sight), `acoustic` `{"bearing":deg
  relative to heading, + is left,"level":0..1}`, `motion` `{"state","target"}`, and `camera`
  `{"format":"jpeg","b64":...}` when a GL renderer exists (needs Pillow; `MUJOCO_GL=egl` on headless
  Linux). The gateway must not forward `sensors/scout` to the browser.
- Fake for perception: `python -m sim.record --seconds 60` writes
  `sim/recordings/scout_backup.jsonl`, one `{"topic":"sensors/scout","data":{...}}` per line, no camera.
- Checks: `bash sim/check.sh`.

## Aftershock and physics route check (T05)
- The floor is a dynamic plate welded to the mocap body `ground` (a moved mocap body carries no
  velocity, so on its own it never drags blocks); the outer shell b1-b5 is braced to the plate.
- Shake: 0.015 m at 4 Hz along x for 2 s, then 1 s settle. In the backup scene it fails the leaning
  slab b10 and the wall b8 it leans on; nothing else moves more than 1 cm.
- `route/proposed` -> `route/verified` from a cached check: an aftershock is run on a copy at start and
  after every change; a route cell is unstable if its (i, j) is within 0.10 m of a block that would move
  (before or after), whatever its k. Grid as perception: cell = floor(coordinate / 0.05).
- Live: `POST /inject {"kind":"aftershock"}` shakes the world (3 s), `POST /inject
  {"kind":"block_added","pos":[x,y,z]}` drops the one spare block `x1`; each publishes `world/change`
  when complete. The Responder (T06) must stop while `world.shaking` is true.
- `python -m sim.demo_aftershock` (viewer) or `--no-viewer`: prediction, shake, moved blocks.

## Photo-to-scene builder with self-critique loop (T07)
- `python -m sim.scene_builder sim/photos/set1/*.jpg`
  Takes 3 to 5 tabletop model photos, sends them to `gemini-4-argon` via `coord/gem.py` (`lead_reasoning`), validates the returned MJCF, runs a 3-second settle physics test (max block drift < 0.05 m), and renders visual critique images (`overview`, `scout_cam`, `side_view`) using local `mujoco.Renderer`.
- Iteration critique images are saved to `sim/generated/iter<k>_<cam>.png`. Visual feedback ("List mismatches between the photos and these renders, then output the corrected MJCF") is fed back to the model for up to 4 rounds.
- The winning MJCF is written to `sim/generated/photo_scene.xml` and published/loaded as `scene/loaded {"scene": "photo", "blocks": [...]}`.
- In `GEMINI_MODE=off`, immediately loads the backup scene (`sim/scenes/backup.xml`), labels the stand-in (`gem.mark_stand_in("scene")`), and prints `[STAND-IN]` to stderr without calling the model.
- In `GEMINI_MODE=replay`, uses cached responses / replay fixtures so repeated test runs cost zero tokens.
- If validation fails after 4 rounds, cleanly falls back to the backup scene with `scene: "backup"`.
- Checks: `python -m pytest sim/tests/test_scene_builder.py -v`.
