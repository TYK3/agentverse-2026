# Paired baseline harness (T24)

Measured snapshot, 2026-11-08: **naive 0/30, AFTERSHOCK 0/30 safe arrivals**, in
468.344 seconds wall time (7 min 48 s). All 60 trials completed. Both policies
recorded zero collapsed-cell entries, but no rescue arrival; this is not evidence
of an adaptive safety advantage. The frozen backup-scene run reached its 60 s
simulation limit. See `results.csv`, `summary.json`, `safe_success.png` and
`provenance.json`. `measured-traces.zip` preserves all 60 raw traces;
`measured-runtime-sources.zip` preserves their exact source files and backup scene.
The published driver differs from the measured source only in import ordering.

To reproduce X2's comparison table from that measured dataset, without another
simulation run:

```sh
python -m tools.eval_compare --traces eval/measured-traces.zip
```

`eval/comparison/comparison.md` and `.json` report casualties matched within 0.5 m
for scoring, reported track IDs, detection/arrival times, unsafe entries, physics checks and
replans. Missing pairs, mixed source snapshots and incomplete telemetry fail.
The baseline disables aftershock-triggered invalidation and physics verification;
its collision stop remains active. This compares bundled policies and does not
isolate the causal effect of one switch. Non-arrivals have no arrival-time value.

```sh
python -m pip install -r requirements.txt -r coord/requirements.txt
python tools/eval.py --runs 30
```

The default uses `tools.eval_sim:run_trial`, a separate measured driver built with
the production sim, perception, planner and Responder classes. It requires the
T05/T06/T09/T10/T11/T13 lane modules; missing capabilities fail without substituting
fakes. Cloud vision/review are disabled and the test operator is explicit. Each
trial has a 60 s simulation limit (the brief's one-minute scenario); its aftershock starts at 25 s independently
of planner choices. It samples the real Responder pose and marks block AABB cells
collapsed when physical displacement after the shake exceeds T05's threshold.
Both initial and current footprints are conservatively included. The temporary
scene varies rubble b11-b15 by +/-4 cm and casualty position within room 3.
Autonomous exploration runs until a casualty is detected and a seen-free approach
cell exists beside its perceived position. Only the observed estimate sets the
navigation goal; the seeded casualty truth is used for scoring arrival.
Arrival is measured from Responder pose within T06's 0.45 m reach of the casualty;
it does not require entering the person's occupied map cell. Mission commands are
not treated as proof of arrival, and all rules/gates keep their production thresholds.

Other drivers use `async def run_trial(*, seed, planner)` where
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
Independent MuJoCo workers (up to 12 CPUs by default, `--workers N` to change)
keep the batch bounded without sharing a mutable world. The default overall budget
is 880 seconds; timed-out/unavailable trials do not become success-rate observations.

To exercise the harness before the real runner is available:

```sh
python tools/eval.py --runs 30 --driver tools.eval_grid:run_trial --output eval/stand-in
```

This explicitly uses T23's grid topology, the naive A* baseline and production T12
AFTERSHOCK routing. Its five named stand-ins include oracle perception and no MuJoCo
verification. Its measured grid-world numbers are **not full-system results** and
must be labelled that way in any submission. They do not validate rescue safety.

The measured adapter wires production classes on a simulation clock; it does not
exercise the browser, voice or wall-clock hub startup. This frozen version still
uses production scene-derived hazard estimates (before Z1), which is disclosed
in the run scope. It does not claim sensor-only hazard prediction. Raw traces
include hashes of every Python lane source and the driver for provenance.
