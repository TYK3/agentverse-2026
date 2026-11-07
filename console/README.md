# console lane: the operator screen

Spec: "What the operator sees on screen" in `docs/aftershock.md`.

Owns: the single browser screen (orbitable Three.js 3D map with cell states, casualty markers and hazard
colours; current and faded previous routes; reasoning log with confidence and model; edge budget meter
and online/offline indicator; command bar with approve and reject buttons and the report button);
and the typed twin of every voice command. Voice itself is the `voice/` lane.

Ships first: the screen running on fixture files, with typed commands.

Owner: see the owner table in `AGENTS.md`. Only this lane's agent edits files here; others ask on the board.
