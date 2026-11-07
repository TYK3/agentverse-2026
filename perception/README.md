# perception lane: map, casualties, hazards

Spec: Functions 2 and 3 of `docs/aftershock.md`.

Owns: the live 3D map with every cell labelled seen, inferred or unknown (only seen counts as confirmed
safe); Scout exploration toward unknown cells and re-scans of uncertain ones; casualty detection that
fuses body pose, thermal and sound direction into a position and confidence (no faces; vitals marked
simulated); and hazard prediction that marks each cell stable, at risk or collapsed, checked against
what the aftershock actually moves.

Ships first: fixture files for the map, casualties and hazards, so the planner and console can start.

Owner: see the owner table in `AGENTS.md`. Only this lane's agent edits files here; others ask on the board.
