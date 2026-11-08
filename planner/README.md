# Planner lane: local routes (T12)

`route.find_route(map_cells, hazards, start, goal)` runs A* on the z=0 grid,
with eight-connected moves. Only explicit `seen`, free cells are traversable;
`at_risk` and `collapsed` cells are excluded. Diagonal moves require both side
cells to be safe. Step cost is distance in metres plus 5 when entering a cell
whose centre is within 0.15 m of an occupied ground cell. Only the ground layer
is used; this is not a robot-footprint or physics check.

Success returns `{"status":"ok","cells":[...],"cost":0.6}` with start and goal
included. Failure returns `{"status":"no_verified_route","needs":"re-look",
"cells":[...]}`: up to eight inferred, unknown or unlisted cells inside the map
bounds, beside the reachable region, ordered nearest the goal first. This list
is for scanning, not movement. It can be empty when only known obstructions
block the route. An unobserved start also returns an empty failure.

## Hub integration

The hub calls `planner.start(bus)`. It subscribes to `map/cells` and `map/hazards`
and returns a `RoutePlanner`; no automatic Responder action is issued.
Cell updates merge by grid coordinate, supporting perception's deltas and full
snapshots. Explicit `unknown` or occupied updates revoke traversability; a
resolution change clears the old grid. Start a new planner for a new scene.
Hazard messages replace the previous hazard list. The caller supplies the start and goal
grid cells (choose a free cell next to the casualty), then:

```python
planner = await start(bus)
# After map/cells and map/hazards arrive:
result = await planner.propose((0, 2, 0), (6, 2, 0), goal_text="deliver water to c1")
```

Each successful call publishes `route/proposed` with
`{"id":"r1","robot":"responder","cells":[...],"goal":"deliver water to c1",
"model":"local-astar"}`. IDs increase per planner instance. Failure publishes
no route. T12 makes no Gemini calls; `local-astar` is the model value required
by issue #20 (the shared contract/schema owner has been notified).

All proposals still require the sim physics check before acting. Physics
verification, online review, confidence and human gates, re-planning, offline
Gemma goal selection and reports are later tasks (T13–T16). Owner: Anthony's
Codex-2, planner lane.

## Run and check

From the repository root, with Python and pytest installed:

```sh
GEMINI_MODE=off python -m pytest planner -q
GEMINI_MODE=off python -m planner.fake_run
```

Or run `bash planner/check.sh` with uv. CI uses this same executable script.
The runner labels its development fixtures on stderr and prints a JSON bus
envelope on stdout. It uses bundled `planner/fixtures/` while T02 is pending;
to feed shared or perception fixtures, provide their paths and endpoints.
Both raw payloads and the hub's `{topic,data}` fixture envelopes are accepted:

```sh
python -m planner.fake_run --map coord/fixtures/map__cells.json \
  --hazards coord/fixtures/map__hazards.json --start 0 0 0 --goal 4 2 0
```

Unreachable routes print the failure result and exit 1. The default development
scene has a single doorway at `[3,2,0]`; marking that cell collapsed blocks it.

## Handover report (T16)

`planner.start(bus)` also attaches a `ReportCollector` as `router.reporter`.
Call `await router.reporter.generate()` or send `operator/command` with text
`report`, `handover report` or `generate report`. The result publishes
`report/handover {json, markdown}` and writes an ignored
`reports/handover_<UTC timestamp>.md` file. The returned result also contains
the local `path`; that filesystem path is not sent to the console.

The collector retains allowlisted map counts, casualty positions/confidence/
clues, simulated vitals, estimated hazards before/after, routes and physics
verdicts, re-plan reasons, action commands and every approval answer with its
operator and time. It never subscribes to sensor images. Action commands are
labelled as commanded; the contract has no delivery-completion event, so the
report does not infer delivery from a command. An exact `log/decision` from the
sim (`model=sim`, `physics=mujoco`, `outcome=done`, `placed <item> at [x, y]`)
records a confirmed simulated placement, matching the T06 Responder's log.

The plain template works with `GEMINI_MODE=off`. When the shared wrapper is
available and enabled, one `coord.gem.ask("fast_subagent", ..., feature="handover_report")`
attempt per collector asks `gemini-3.8-flash` for structured JSON. The draft may
rewrite the summary; recorded sections must match exactly or it falls back to
the template. Errors, invalid JSON, changed facts and timeouts use the same
template. Repeated requests refresh the facts and never spend another model
call; an old draft is discarded after new events. Stand-ins are labelled.

Replay the development handover fixtures with:

```sh
GEMINI_MODE=off python -m planner.report_run
```

`bash planner/check.sh` includes this demo and the report tests. The check uses
pytest and Pydantic to validate the published report against the shared schema.

### Remote paramedic reports (ref Y6)

`paramedic report` and `remote paramedic report` also generate a handover. Its
existing `report/handover` envelope includes `json.paramedic_reports[]` and a
Markdown section for each casualty: scene coordinates in metres with observation
time, detection confidence and sensor clues; simulated breathing rate; the six
Y5 response categories; self-reported pain locations; requested actions,
observed sim action outcomes and confirmed simulated deliveries, human gate
decisions and unknown information.
Reports retain the last observation of casualties absent from a later list and
label it as such. Detection confidence never becomes medical certainty. A
missing reply is unknown, and `none_reported` pain is not a diagnosis.

The optional dialogue reader calls the public `voice.GUIDE.summary(cid)` from Y5
only if the voice lane is already loaded. It does not start voice or make a model
call. Until Y5 is available, symptoms and answers remain explicitly unknown.
Tests and other local integrations can inject `dialogue_summary(cid)` into
`ReportCollector`. Only known response categories and body parts are retained;
no face data, audio or raw transcripts are copied. Y3 has no published triage
interface yet, so the report does not invent a triage assessment.

Actions are associated only with routes whose goal ends exactly in ` to <id>`.
Unassociated actions remain in the global handover. For repeated supply items,
placement logs use the sim's active route; when no route can be established
unambiguously the delivery remains unassigned. Commands never prove treatment
or delivery, and this collector never authorizes robot motion or medical steps.

`GEMINI_MODE=off python -m planner.paramedic_run` replays a labelled synthetic
two-casualty fixture (one simulated delivery, one denied human gate). The same
fixture is included in `bash planner/check.sh`; real audio and patient input are
not part of this demo.

## Human approval and tasks (T14)

On the hub, automatic casualty handoff first waits for Y3's accepted
`casualty/triage` supply choice. An uncertain choice needs its clinical approval;
that approval alone does not dispatch an arm command or grant route permission.
The handoff honours the accepted kit item, constructs a route to a mapped free
cell beside the casualty, and enters the normal physics/confidence/movement
checks. If that item or its found material is unavailable, it holds for another
choice instead of silently substituting a different supply. Standalone handoff
callers can retain the previous lane-only behaviour with `require_triage=False`;
`planner.start(bus)` enables the integrated mode.

The hub also enables `defer_approved_actions` on the loop: an accepted navigation
answer queues dispatch on the next event-loop turn so the sim's synchronous
approval handler can run before move commands. Dispatch still checks the route
ID and current risks; a scene change cancels stale work. Standalone loop callers
retain immediate awaited dispatch by default.

A permit freeze keeps the same casualty delivery assigned and does not spend a
collision retry. The handoff consumes the measured `responder/pose` to update
the next route's start; if that position is unobserved, routing holds for a
re-look rather than returning to the old origin. A permit re-earned by fresh
observation re-proposes the paused delivery from that current pose and repeats
physics/confidence checks. It does not replay the original route's waypoints.

On the Scout's fine grid, each candidate move checks the swept forward chassis
footprint against measured occupied squares, including the collision guard's
0.19 m front clearance. This prevents a route from turning too late beside a
wall even when its centre cells are free. Handoff stopping cells also leave
room for the chassis and final heading; the arm places the supply ahead.
Coarse development maps retain their existing routing behaviour. These checks
cannot establish that stale free cells behind a newly sensed surface remain
free: fresh mapping and the live collision guard still govern movement.

`planner/tests/test_route_footprint.py` drives the real MuJoCo Responder through
two corner detours, three right-angle corridors and a casualty approach, with
its collision guard unchanged. Run it with MuJoCo, NumPy, pytest, Pydantic and
FastAPI installed; the optional MuJoCo cases skip if MuJoCo is unavailable.

`router = await planner.start(bus)` attaches the verification loop as
`router.loop`, plus the budget publisher as `router.task`. Use that existing loop.
`await loop.mission(start, goal, item="water", action="deliver")` dispatches
`move`, `place_supply`, `release` after physics verification and the confidence
gate. `action="grip"` adds `grip` after `move` and always requests human approval.
The current wire `item` names supplies only. Gripping a debris block requires
an agreed block-target field; this API does not claim to clear an obstacle.
A route crossing a newly reported `at_risk` cell requests `enter_at_risk` approval.
Each request is published as `gate/request {id,kind,summary,route}` and expires
after 60 seconds. It does not block other bus messages while waiting.

Only a matching, literal `approved: true` in `gate/answer` unlocks that request;
denials and timeouts leave the Responder idle and record the reason in
`log/decision`. Duplicate and stale answers cannot replay an action. A new
mission, replacement route or aftershock cancels the outstanding approval.
An approval cannot override a failed physics check, occupied or unobserved
cells, or a collapsed cell. The loop checks these again before every command.

`await loop.prepare_emergency_call(summary)` displays the prepared message in
`gate/request` with kind `emergency_call`. Approval records the prepared message
for the operator; it emits no robot action and places no call.

Action messages are submitted in order for the sim to execute. The current
contract has no action-completion acknowledgements; publishing an action does
not prove that the robot arrived or delivered supplies. Sim must hold and drop
queued work on an aftershock, while this loop cancels any remaining dispatch.
`gate_timeout` can be shortened in tests; the production default is 60 seconds.
