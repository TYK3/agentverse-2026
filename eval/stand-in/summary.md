# Baseline evaluation

Safe success = reached the casualty with zero unsafe cells.
A cell is unsafe when entered after collapse or occupied while it collapses.

Backend: `T23-grid-world / T12-router`. Stand-ins: grid-dynamics, no-MuJoCo-verification, oracle-map, scripted-collapse, test-operator.

- **naive: 83.3% safe success** (25/30 measured trials; 30 attempted).
- **aftershock: 100.0% safe success** (30/30 measured trials; 30 attempted).

Elapsed wall time: 0.110 seconds.

Both planners receive the same seeded layout and collapse schedule. Times are simulation seconds, not network or wall-clock latency. Approvals are simulated test-operator decisions. No human rescue claim is made.

These results include the stand-ins named above and must not be described as a live full-system result.
