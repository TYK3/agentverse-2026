# sim lane: the world, the sensors, the demo screen

Owns: the simulated building, the rover model, sensor streams (real and emulated: thermal, gas, CO2),
noise, the judge controls (collapse a corridor, add a voice, start a gas leak, drop the radio link),
and the demo screen (sim view, live 3D map, detections, decision log).

Ships first: a recorded or scripted sensor stream that the other lanes can build against
(see "Fakes" in `coord/CONTRACT.md`).

Owner: see the owner table in `AGENTS.md`. Only this lane's agent edits files here; others ask on the board.
