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

## Human approval and tasks (T14)

Use `await planner.loop.start(bus, router)` to attach the verification loop.
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
