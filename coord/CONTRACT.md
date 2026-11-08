# Interfaces between lanes

Every boundary one lane calls on another goes here first, before code. Change it with a PR that
touches nothing else, and post the change on the board tagging the affected lanes.

Transport proposed by T02 (#10): one Python process with an asynchronous topic bus and a FastAPI
WebSocket gateway at `ws://localhost:8000/ws`. The wire envelope is
`{"topic":"map/cells","data":{...}}`; array payloads remain arrays in `data`.
Lanes expose `async def start(bus)` and use `bus.subscribe(topic, callback)` (sync or async callback)
and `await bus.publish(topic, data)`. Every publish is validated against `coord.messages.TOPICS`.
Browser clients may publish only `operator/command`, `gate/answer` and `status/link`; invalid messages close the
connection with code 1008 before dispatch. The gateway forwards all topics except `sensors/scout`
and replays its latest 200 forwarded envelopes to each new connection. This is bounded event
history, not a complete map snapshot: perception also publishes full map snapshots every 5 s (T08).

The shapes below are JSON.
Coordinates are metres in the scene frame; `cell` is a grid index `[i, j, k]`; `t` is seconds since the
run started. These are first drafts: the owning lane refines them by PR.

## Messages
| Name | Producer | Consumer | Shape |
|---|---|---|---|
| `scene/loaded` | sim | all | `{"scene":"backup"|"photo"|"tower"|"building",|"photo"|"tower",\|"photo","blocks":[{"id":"b7","label":"wall","pos":[x,y,z],"size":[x,y,z]}]}` |
| `sensors/scout` | sim | perception, planner (L1 permits trace the LiDAR) | LiDAR ranges, camera frame, thermal grid, acoustic `{"bearing":deg,"level":0..1}`, pose |
| `map/cells` | perception | planner, console | `{"t":0,"res":0.05,"cells":[{"cell":[i,j,k],"state":"seen"\|"inferred"\|"unknown","occupied":true}]}` |
| `map/casualties` | perception | planner, console | `[{"id":"c1","pos":[x,y,z],"confidence":0.8,"clues":["pose","thermal","sound"],"vitals":{"breathing_rate":14,"simulated":true}}]` |
| `map/hazards` | perception | planner, console | `[{"cell":[i,j,k],"status":"stable"\|"at_risk"\|"collapsed","why":"unsupported wall b7","estimate":true}]` |
| `scout/goto` | planner, perception | sim | `{"target":[x,y,z],"reason":"re-look at cell [3,4,0]"}` |
| `route/proposed` | planner | sim (physics check), console | `{"id":"r3","robot":"responder","cells":[[i,j,k],...],"goal":"deliver water to c1","model":"gemini-4-argon"\|"gemma-4-local"}` |
| `route/verified` | sim | planner, console | `{"id":"r3","ok":false,"unstable_cells":[[i,j,k]],"detail":"block b7 falls"}` |
| `gate/decision` | planner | console | `{"id":"d12","outcome":"act"\|"relook"\|"refer","confidence":0.6,"reason":"one line"}` |
| `gate/request` | planner | console | `{"id":"g4","kind":"risky_move"\|"enter_at_risk"\|"emergency_call","summary":"...","route":"r3"}` |
| `gate/answer` | console | planner | `{"id":"g4","approved":true,"by":"operator"}` |
| `responder/action` | planner | sim | `{"action":"move"\|"place_supply"\|"grip"\|"release","route":"r3","item":"water"\|"first_aid_kit"\|"radio"\|"bandage"\|"splint"\|"thermal_blanket","block":"b11"}` (`block` optional, Y2: grip/release that block, e.g. debris to clear or a board used as a splint) |
| `operator/command` | console (typed), voice (spoken) | planner, console | `{"text":"send water to the back room","source":"voice"\|"typed"}` (after any change of mind is resolved) |
| `world/change` | sim | planner, perception, console | `{"kind":"aftershock"\|"block_added","t":0,"moved_blocks":["b7"]}` |
| `world/debris` | sim | console, scoring (never perception: sim truth) | `{"t":0,"truth":true,"events":[{"id":"b8","kind":"moved"\|"fell"\|"settled","pos":[x,y,z],"moved_m":0.7,"drop_m":0.37}],"stacks":[{"ids":["b10","b8"],"risk":0.69,"worst":"b10","tilt_deg":30,"overhang":0.83,"motion_m":0,"top_z":0.72,"min_xy":[x,y],"max_xy":[x,y],"unstable":true}]}` (Y8) |
| `log/decision` | planner | console | `{"t":0,"perception":"...","model":"...","physics":"...","outcome":"...","reason":"one line"}` |
| `permit/route` | planner | sim (Responder stops and refuses moves while `granted` is false), console (evidence per action) | `{"route":"r3","granted":false,"t":12.3,"reason":"revoked: LiDAR hit inside the route at 2 cell(s)","evidence":[{"kind":"verified"\|"clear"\|"shift"\|"hazard"\|"fresh_scan","detail":"...","t":12.3}]}` (L1: revoked only by sensed change, re-earned only by a fresh scan of every route cell) |
| `status/link` | sim, planner or console offline toggle | planner, console | `{"online":false}` |
| `status/budget` | planner | console | `{"device":"<open>","mem_mb":0,"model":"gemma-4-e2b","ms_per_step":0,"limit":{...}}` |
| `say` | planner | voice, console (shown as text) | `{"to":"casualty"\|"operator","intent":"first_aid"\|"guide_exit"\|"reassure","text":"...","lang":"auto"}` |
| `casualty/reply` | sim (persona answers a `say` to the casualty), voice (mic speech-to-text, later) | voice, console | `{"id":"c1","t":12.3,"text":"yes, my leg hurts","source":"sim"\|"mic"\|"typed","level":0.6}` (G3: what one casualty said back, in English; `level` 0..1 optional loudness) |
| `casualty/contact` | voice | planner (supply choice, Y2), console, report | `{"id":"c1","t":40.1,"status":"talking"\|"done"\|"unresponsive"\|"stopped","turns":4,"max_turns":8,"facts":{"responsive":true,"hurt":["leg"],"bleeding":false},"injuries":["leg hurts, may be broken"],"receipts":["gem-..."]}` (G3: the bounded dialogue so far; `facts` values are true/false/null or lists of short strings; `receipts` are coord.gem call ids) |
| `report/handover` | planner | console | Map, casualties with confidence, hazards, routes and re-plans, supplies delivered, human approvals |
| `status/gemini` | hub | console | `{"mode":"off"\|"replay"\|"live","calls_last_hour":0,"stand_ins":["vision","tts"]}`, published every 2 s from `coord.gem.status()` |
| `gemini/receipt` | hub from `coord.gem` | console, report | Completed call receipt (G1), shape below; browser read-only |

## T02 schema details (proposed, #10)

- `coord/fixtures/<topic with / replaced by __>.json` contains the whole wire envelope, not just
  its payload. These are labelled development examples, never a claimed live run.
- `sensors/scout`: `{"t":0,"pose":{"pos":[x,y,z],"yaw":0},"lidar":[1.2,6.0],
  "camera":null,"thermal":[[0.1,0.9]],"acoustic":{"bearing":0,"level":0.5}}`.
  `lidar` is a full horizontal sweep beginning at world +x, evenly spaced counter-clockwise;
  ranges are metres (T04, PR #42). `camera` is `{"format":"jpeg","b64":"..."}`,
  a base64 JPEG string or null (recordings omit images).
  Thermal is a rectangular array of intensities in 0..1; acoustic bearing is degrees relative to yaw.
  `t` and `camera` may be omitted from a recording. Sensor frames go only to local subscribers and
  are never retained in gateway history or replayed to browsers (T04).
- T04 may include `motion: {"state":"idle"|"moving"|"arrived"|"blocked",
  "target":[x,y]|null}`. Motion is local sensor metadata, not a browser event.
- `sensors/scout` may include `points: [[x,y,z], ...]`: up to 2048 points from the Scout's depth
  camera (Y9), already in the scene frame (metres), downsampled. Perception (Z1) scores pile stability
  from them; without them it maps from the 2D LiDAR alone. Sending them in every other frame or less is enough.
  `points_from: [x,y,z]` (optional) is where the camera was for that frame, so perception can mark
  the space along each ray as free and tell moving debris from a new viewpoint (L5).
- `map/hazards` cells may carry `exclusion: true`: a keep-out zone around debris whose motion the
  Scout sensed (L5). Routes never pass through it. It is a precaution from observed motion, not a
  collapse prediction, and it is lifted only after fresh scans of the zone show no further motion.
- `scene/loaded` block `size` is MuJoCo half-extents in metres (T03); Three.js uses `2 * size`.
- T05 publishes `world/change.kind="block_added"` after an operator-injected block lands.
  It carries the block id in `moved_blocks`, invalidates the prior route and triggers a re-scan
  like an aftershock. `t` remains seconds since the run began; no extra position field is needed.
- `map/cells` may include the optional nonnegative integer `hits` in each cell (T08).
- `route/proposed.model` is a nonempty provenance string, including `local-astar` for T12 under
  POLICY #8. The two model names in the table are examples; core routing never requires Gemini.
- `status/budget.limit` is an object of named nonnegative numeric limits; device, model, memory and
  step latency remain the fields in the table. The edge device itself remains an open decision.
- `report/handover` is `{"json":{...},"markdown":"..."}` (T16). `json` contains the structured
  summary, casualties, hazards, actions, approvals and open risks; this inner report is extensible.
- `status/gemini` uses the shape proposed in PR #39: `{"mode":"off","calls_last_hour":0,
  "stand_ins":[]}`. The hub publishes `coord.gem.status()` every 2 s once T26 is available; it
  makes no model calls. Until T26 merges, the publisher is skipped with a logged warning.

## G1 Gemini receipts

`gemini/receipt` has `id` (unique `gem-...` invocation ID), `schema_version: 1`,
`started_at` (UTC ISO timestamp), `feature`, `model_key`, nullable
`model_requested`/`model_reported`, `mode: off|replay|live`,
`source: none|disabled|cache|live`, `outcome: ok|off|error|cap_reached`, nullable
`route` (exactly the `permit/route.route` ID) and caller-owned `evidence_ids: [str]`.
It also includes nullable `provider_id`, `source_call_id`, `usage` (provider token
counts, nonnegative integers), `request_sha256`/`output_sha256`, `cache_write_error`,
nonnegative `elapsed_ms`, and `live_attempts` counting the `sdk_called: true`
entries in `attempts: [{attempt: int>=1, sdk_called: bool, outcome: ok|error,
error_type: str|null}]`. Optional `error_type` contains the exception type only.

Replay has a new invocation ID and zero live attempts, with no current provider
ID/usage. Optional `cache_origin: {id,provider_id,model_requested,model_reported,
usage}` attributes the original live call only when its cached output hash
matches; its fields are nullable for legacy caches. Disabled calls have outcome
`off`, no provider ID/usage and zero attempts. No prompt, media, model response
text or exception text is carried. No receipt grants movement; physics and L1
permission evidence remain separate and join by `route`. The hub forwards each
completed receipt once per publisher lifetime; its existing 200-event replay bound
still applies. This does not claim receipt coverage for existing direct Live
session callers that only use `count_call()`.

## Rules the shapes encode

- Only `seen` cells count as confirmed safe. A route through `inferred` or `unknown` cells is a re-look,
  not an act.
- No message carries a face or an image crop of a person; casualties are positions and confidences.
- Anything marked `simulated` or `estimate` is shown that way on screen and in the report.
- `emergency_call` and risky moves never happen without a matching `gate/answer` with `approved: true`.

## Fakes
Each lane ships a fake of what it provides, so nobody waits:
- sim: the hand-built backup scene and a recorded `sensors/scout` stream; a physics check that always
  answers.
- perception: fixture `map/cells`, `map/casualties` and `map/hazards` files, before and after the
  aftershock.
- planner: a scripted sequence of `route/proposed`, `gate/*`, `log/decision` and `say` messages.
- console: a typed command line that sends `operator/command` and `gate/answer`.
- voice: a text-only stand-in that prints `say` messages and turns typed text into `operator/command`.
