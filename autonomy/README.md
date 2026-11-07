# autonomy lane: the rover's decisions

Owns: the mission manager (explore, investigate a clue, talk, do a task, return), where to look next
(frontiers weighted by clues), what to do for each person (lead out, deliver supplies, leave a beacon,
mark top priority), safety and fail-safes (battery, drops, gas, never report "safe"), re-planning when
the world changes, the decision log, and the handover report.

Ships first: a mission manager that runs on the fake map and logs every decision with its reason.

Owner: see the owner table in `AGENTS.md`. Only this lane's agent edits files here; others ask on the board.
