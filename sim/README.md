# sim lane: the world and the robots

Spec: Function 1, the sensor half of Function 2, and the aftershock in Function 3 of `docs/aftershock.md`.

Owns: the MuJoCo scene of the tabletop collapsed building (the photo-to-scene builder with
`gemini-4-argon` and its self-critique loop, plus the hand-built backup scene), the Scout and Responder
robot models and the gripper, the simulated sensors (ray-cast LiDAR, camera, thermal, acoustic), the
scripted aftershock, and the physics check that runs a proposed route and reports unstable cells.

Ships first: the hand-built backup scene with both robots and a recorded sensor stream, so the other
lanes can build against it before the scene builder works.

Owner: see the owner table in `AGENTS.md`. Only this lane's agent edits files here; others ask on the board.
