# perception lane: SLAM, the map, "is that a person?"

Owns: 3D SLAM (use an existing package, don't write SLAM), the driveable map, the semantic layer
(people, hazards, doors, supplies pinned in 3D), and person-candidate fusion (voice, heat, shape, CO2
into one confidence; two different clues before "found").

Ships first: a fake map and fake person candidates from a fixture file.

Owner: see the owner table in `AGENTS.md`. Only this lane's agent edits files here; others ask on the board.
