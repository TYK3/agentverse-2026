# perception lane: map, casualties, hazards

Spec: Functions 2 and 3 of `docs/aftershock.md`.

Owns: the live 3D map with every cell labelled seen, inferred or unknown (only seen counts as confirmed
safe); Scout exploration toward unknown cells and re-scans of uncertain ones; casualty detection that
fuses body pose, thermal and sound direction into a position and confidence (no faces; vitals marked
simulated); and hazard prediction that marks each cell stable, at risk or collapsed, checked against
what the aftershock actually moves.

Ships first: fixture files for the map, casualties and hazards, so the planner and console can start.

Owner: see the owner table in `AGENTS.md`. Only this lane's agent edits files here; others ask on the board.

## Hazards (T11, `perception/hazards.py`)

On `scene/loaded` and on every `world/change`, perception publishes the whole `map/hazards` list (it
replaces the previous one). Each block's plan-view footprint is labelled on the ground layer k=0
(the layer map/cells uses), always with `estimate: true`:

- a wall taller than it is wide with under 50% of its base resting on something: `at_risk`;
- a rubble block whose centre is outside its contact patches, or with nothing beneath it: `at_risk`;
- after `world/change`: moved blocks' cells `collapsed`, cells within 0.15 m of them `at_risk`.

In the backup scene only b10 (the slab leaning on b8) is `at_risk` before the shake. Fixtures:
`perception/fixtures/map_hazards_before.json` and `map_hazards_after.json` (b10 and b11 moved).
