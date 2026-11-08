# console lane: the operator screen

Spec: "What the operator sees on screen" in `docs/aftershock.md`.

Owns: the single browser screen (orbitable Three.js 3D map with cell states, casualty markers and hazard
colours; current and faded previous routes; reasoning log with confidence and model; edge budget meter
and online/offline indicator; command bar with approve and reject buttons and the report button);
and the typed twin of every voice command. Voice itself is the `voice/` lane.

Ships first: the screen running on fixture files, with typed commands.

Owner: see the owner table in `AGENTS.md`. Only this lane's agent edits files here; others ask on the board.

## Run and verify

Use `npm ci`, then `npm run dev` from `console/`. Open `http://localhost:5173/?fake=1`
for shared hub fixtures plus `fixtures/panels.json` (over-budget telemetry and a second queued approval).
Fake sends are printed as `[bus fake outgoing]` JSON in the browser console; live sends appear as
WebSocket frames at `ws://localhost:8000/ws`. Fake mode never performs rescue actions.

`npm run build` checks TypeScript and bundles the console. For browser checks, run
`npx playwright install chromium`, then `npm test`. Tests cover fixture updates, approval queues,
exact outgoing WebSocket envelopes, and retaining requests when a send fails.

The `o` key toggles `status/link` once link telemetry arrives; typing in inputs does not toggle it.
Budget limits use `limit.mem_mb` and `limit.ms_per_step`; missing limits are labelled unset.
The mic button is a disabled hook for the voice lane. Reports render headings and text safely;
embedded HTML is displayed as text. SIMULATED and ESTIMATE labels remain visible for flagged data.
