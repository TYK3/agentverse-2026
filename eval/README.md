# Paired baseline harness (T24)

```sh
python -m pip install -r requirements.txt
python tools/eval.py --runs 30
```

The default consumes `tools.run_scenario:eval_trial`, a real T23 trial driver.
Until that measured-trajectory API is available, it fails before reporting any
performance numbers. A driver is `async def eval_trial(*, seed, planner)` where
planner is `naive` or `aftershock`. Return this trace:

```json
{
  "seed": 0,
  "planner": "aftershock",
  "goal": [4, 2, 0],
  "backend": "actual runtime description",
  "stand_ins": [],
  "scenario_sha256": "sha256 of the seeded layout and exogenous collapse schedule",
  "completed": true,
  "events": [
    {"t": 0, "kind": "position", "cell": [0, 0, 0]},
    {"t": 1, "kind": "route", "id": "r1"},
    {"t": 2, "kind": "approval", "id": "g1", "approved": true},
    {"t": 3, "kind": "collapsed", "cells": [[2, 1, 0]]},
    {"t": 4, "kind": "position", "cell": [4, 2, 0]}
  ]
}
```

Positions must be observed from the Responder, not inferred from route or delivery
commands. Times are ordered, finite simulation seconds from the start of the trial.
Both planner trials must use the same seeded rubble positions, casualty cell and
collapse schedule (enforced by the fingerprint). The trial ends at arrival or its
simulation time limit; `completed` means the trial ran, not that it succeeded.
Missing telemetry or an unavailable runtime is incomplete, not a measured failure.

Unsafe cells are unique cells entered after collapse or occupied when they collapse.
Revisiting the same unsafe cell counts once. A collapse later in a cell already
vacated does not count. Safe success requires observed arrival and zero unsafe cells.
Routes and approved gate IDs are deduplicated for re-plan and approval counts.

Outputs: `results.csv`, `safe_success.png`, `summary.json`, `summary.md`, and raw
`traces/<seed>_<planner>.json`. Incomplete coverage and stand-ins are explicit in
the CSV, summary and chart. A full run is capped below 15 minutes; each trial has
a timeout. Exceptions stop with a nonzero code and retain completed CSV pairs.

To exercise the harness before the real runner is available:

```sh
python tools/eval.py --runs 30 --driver tools.eval_grid:run_trial --output eval/stand-in
```

This explicitly uses T23's grid topology, the naive A* baseline and production T12
AFTERSHOCK routing. Its five named stand-ins include oracle perception and no MuJoCo
verification. Its measured grid-world numbers are **not full-system results** and
must be labelled that way in any submission. They do not validate rescue safety.
