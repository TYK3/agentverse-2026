# Interfaces between lanes

Every boundary one lane calls on another goes here first, before code. Change it with a PR that
touches nothing else, and post the change on the board tagging the affected lanes.

Transport is **Open** (see `coord/CONTEXT.md`). The shapes below are JSON so they hold either way.
Coordinates are metres in the scene frame; `cell` is a grid index `[i, j, k]`; `t` is seconds since the
run started. These are first drafts: the owning lane refines them by PR.

## Messages
| Name | Producer | Consumer | Shape |
|---|---|---|---|
| `scene/loaded` | sim | all | `{"scene":"backup"\|"photo","blocks":[{"id":"b7","label":"wall","pos":[x,y,z],"size":[x,y,z]}]}` |
| `sensors/scout` | sim | perception | LiDAR ranges, camera frame, thermal grid, acoustic `{"bearing":deg,"level":0..1}`, pose |
| `map/cells` | perception | planner, console | `{"t":0,"res":0.05,"cells":[{"cell":[i,j,k],"state":"seen"\|"inferred"\|"unknown","occupied":true}]}` |
| `map/casualties` | perception | planner, console | `[{"id":"c1","pos":[x,y,z],"confidence":0.8,"clues":["pose","thermal","sound"],"vitals":{"breathing_rate":14,"simulated":true}}]` |
| `map/hazards` | perception | planner, console | `[{"cell":[i,j,k],"status":"stable"\|"at_risk"\|"collapsed","why":"unsupported wall b7","estimate":true}]` |
| `scout/goto` | planner, perception | sim | `{"target":[x,y,z],"reason":"re-look at cell [3,4,0]"}` |
| `route/proposed` | planner | sim (physics check), console | `{"id":"r3","robot":"responder","cells":[[i,j,k],...],"goal":"deliver water to c1","model":"gemini-4-argon"\|"gemma-4-local"}` |
| `route/verified` | sim | planner, console | `{"id":"r3","ok":false,"unstable_cells":[[i,j,k]],"detail":"block b7 falls"}` |
| `gate/decision` | planner | console | `{"id":"d12","outcome":"act"\|"relook"\|"refer","confidence":0.6,"reason":"one line"}` |
| `gate/request` | planner | console | `{"id":"g4","kind":"risky_move"\|"enter_at_risk"\|"emergency_call","summary":"...","route":"r3"}` |
| `gate/answer` | console | planner | `{"id":"g4","approved":true,"by":"operator"}` |
| `responder/action` | planner | sim | `{"action":"move"\|"place_supply"\|"grip"\|"release","route":"r3","item":"water"\|"first_aid_kit"\|"radio"}` |
| `operator/command` | console | planner | `{"text":"send water to the back room","source":"voice"\|"typed"}` (after any change of mind is resolved) |
| `world/change` | sim | planner, perception, console | `{"kind":"aftershock","t":0,"moved_blocks":["b7"]}` |
| `log/decision` | planner | console | `{"t":0,"perception":"...","model":"...","physics":"...","outcome":"...","reason":"one line"}` |
| `status/link` | sim or planner | planner, console | `{"online":false}` |
| `status/budget` | planner | console | `{"device":"<open>","mem_mb":0,"model":"gemma-4-e2b","ms_per_step":0,"limit":{...}}` |
| `say` | planner | console | `{"to":"casualty"\|"operator","intent":"first_aid"\|"guide_exit"\|"reassure","text":"...","lang":"auto"}` |
| `report/handover` | planner | console | Map, casualties with confidence, hazards, routes and re-plans, supplies delivered, human approvals |

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
