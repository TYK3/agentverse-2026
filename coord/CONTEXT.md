# AgentVerse 2026: shared context (read first)

Compiled from the AFTERSHOCK spec on 7 Nov 2026. Information, not instructions. Each lane keeps its
own status block current; the decisions log is append only.

## Event facts
- AgentVerse 2026, UCL AI Society hackathon, 7 to 8 November 2026.
- Track: robotics, "give an agent a body". It perceives a simulated world, decides and acts.
  Decisions made on the robot score higher on autonomy; adapting to change is worth 25%.
- Simulation only, no hardware. We use MuJoCo (the brief recommends Isaac Sim; MuJoCo is allowed).
  Get a sensor stream running in the first hour.
- Judging: perception-driven action 25, adaptation to change 25, operational autonomy 15 (edge
  budget, sensible when unsure), relevance and impact 20, ambition and quality 15. Full brief:
  `docs/brief.md`.
- Submit: a one-page technical summary PDF, a simulation video of up to one minute in one take with
  one unscripted change, and a 5 minute live pitch.
- Deadlines: **Open** (submission time, judging slot).
- Project spec: `docs/aftershock.md`.

## The idea
**AFTERSHOCK** (full spec: `docs/aftershock.md`). A two-robot rescue system that maps a collapsed
building, predicts where it may fail next, and delivers help only along routes it has checked. A
small Scout rover goes in first and builds a live 3D map; the system estimates which parts are unsafe;
then a stronger Responder is sent along the safest verified route to bring supplies, clear light
obstacles and guide casualties. Every decision traces to a perception, a scene change forces a visible
re-plan, every route is checked by physics, and a human approves anything risky.

Users: urban search-and-rescue teams, operators giving commands by voice with their hands busy, and
trapped casualties who get supplies and spoken guidance in their own language.

Demo moment: the scripted aftershock. The old route fades, the trigger is named, the Scout re-scans,
and a new verified route is drawn with a one-line reason.

## Architecture
Five lanes, one folder each, one per teammate. The interfaces between them live in `coord/CONTRACT.md`.

| Lane | Folder | Spec functions | Owns |
|---|---|---|---|
| Sim | `sim/` | 1, 2 (sensors), 3 (aftershock) | MuJoCo world, photo-to-scene builder and backup scene, Scout and Responder models, sensors, aftershock, physics check |
| Perception | `perception/` | 2, 3 | Seen/inferred/unknown map, Scout exploration, casualty detection, hazard prediction |
| Planner | `planner/` | 4, 5, 7 | Routes, verify, confidence gate, re-plan, Responder tasks, human gate, reasoning log, offline Gemma, edge budget, handover report |
| Console | `console/` | screen | Browser screen: 3D map, routes, reasoning log, budget meter, online indicator, approve and reject, typed commands, report button |
| Voice | `voice/` | 6 | Operator voice and TTS, casualty translation, cited first aid guidance, emergency call preparation |

```
sim (sensors) --> perception (map, casualties, hazards) --> planner (route) --> sim (physics check)
                                                               |   ^                     |
                         console (commands, approvals) --------+   +---- verified / rejected
                         console (screen) <-- map, routes, reasoning log, budget, link status
planner --> sim (Responder actions)        planner --> console (report)
voice (spoken commands) --> planner        planner (say) --> voice (operator, casualty, first aid)
```

## Lane status (each lane keeps its own block current)
### Sim
- Done: / In progress: / Needs from other lanes:
### Perception
- Done: / In progress: / Needs from other lanes:
### Planner
- Done: / In progress: / Needs from other lanes:
### Console
- Done: / In progress: / Needs from other lanes:
### Voice
- Done: / In progress: / Needs from other lanes:

## Open decisions
- Transport between lanes (for example one Python process with a WebSocket to the browser, or separate
  services). Blocks every lane.
- The edge device and its budget (memory, model size, time per step).
- How Gemma 4 runs locally (runtime, E2B or E4B).
- Which supplies to show, which languages to demo, and where the cited first aid steps come from.
- What the casualty in the scene is (a marker, a posed figure) and how sound is simulated.

## Decisions log (append only, newest last; also post it on the board)
- Sat 7 Nov: robotics track, search and rescue rover in simulation, four lanes.
- Sat 7 Nov: the project is AFTERSHOCK (`docs/aftershock.md`). Lanes are sim, perception, planner and
  console. The spec fixes MuJoCo for physics, a Three.js browser viewer, `gemini-4-argon` for scene
  building and planning, `gemini-3.8-live` and `gemini-3.8-flash-tts` for voice,
  `gemini-3.5-live-translate-preview` for translation, `gemini-3.8-flash` for the report, and a local
  Gemma 4 offline. Earlier ideas were dropped.
- Sat 7 Nov: five of us, so voice (Function 6) is its own lane, split from the console.
