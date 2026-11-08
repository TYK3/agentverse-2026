# Baseline evaluation

Safe success = reached the casualty with zero unsafe cells.
A cell is unsafe when entered after collapse or occupied while it collapses.

Backend: `MuJoCo + production perception/router/gate/Responder`. Stand-ins: cloud-route-review-off, cloud-vision-off, test-operator.

- **naive: 0.0% safe success** (0/30 measured trials; 30 attempted).
- **aftershock: 0.0% safe success** (0/30 measured trials; 30 attempted).

Elapsed wall time: 468.344 seconds.

Both planners receive the same seeded layout and collapse schedule. Times are simulation seconds, not network or wall-clock latency. Approvals are simulated test-operator decisions. No human rescue claim is made.

These results include the stand-ins named above and must not be described as a live full-system result.
