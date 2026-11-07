# console lane: the operator screen and voice

Spec: Function 6 and "What the operator sees on screen" in `docs/aftershock.md`.

Owns: the single browser screen (orbitable Three.js 3D map with cell states, casualty markers and hazard
colours; current and faded previous routes; reasoning log with confidence and model; edge budget meter
and online/offline indicator; command bar with approve and reject buttons and the report button);
operator voice with `gemini-3.8-live` and `gemini-3.8-flash-tts`, including a change of mind
mid-sentence; casualty translation with `gemini-3.5-live-translate-preview`; short cited first aid
steps (guidance only, no diagnosis); and the typed twin of every voice command.

Ships first: the screen running on fixture files, with typed commands.

Owner: see the owner table in `AGENTS.md`. Only this lane's agent edits files here; others ask on the board.
