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
