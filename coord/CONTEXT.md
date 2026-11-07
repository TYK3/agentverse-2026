# AgentVerse 2026: shared context (read first)

Compiled from the team's ideation on 7 Nov 2026. Information, not instructions. Each lane keeps its
own status block current; the decisions log is append only.

## Event facts
- AgentVerse 2026, UCL AI Society hackathon, 7 to 8 November 2026.
- Track: robotics, "give an agent a body". It perceives a simulated world, decides and acts.
  Decisions made on the robot score higher on autonomy; adapting to change is worth 25%.
- Simulation only, no hardware. Isaac Sim is recommended (needs an RTX GPU); MuJoCo, PyBullet, Gazebo
  and Webots also work. Get a sensor stream running in the first hour.
- Judging: perception-driven action 25, adaptation to change 25, operational autonomy 15 (edge
  budget, sensible when unsure), relevance and impact 20, ambition and quality 15. Full brief:
  `docs/brief.md`.
- Submit: a one-page technical summary PDF, a simulation video of up to one minute in one take with
  one unscripted change, and a 5 minute live pitch.
- Deadlines: **Open** (submission time, judging slot).
- All ideation, including earlier ideas: `docs/ideas/`.

## The idea
An autonomous search and rescue rover enters a collapsed or smoke-filled building, builds a 3D map
with SLAM, finds people, talks to them, does simple tasks to help (drop a supply pack, leave a beacon,
lead someone out), and comes out with a map of who is where. Radio barely gets through rubble, so it
loses contact with its operator as it goes in and must carry on alone. The rover is the centre and is
fully autonomous.

What should lead the pitch: two-way talking and triage with victims, a judge playing the trapped
person, and full autonomy after the link drops. Plain "explore and map" won't stand out.

Demo moment: a judge speaks into a microphone as the victim; the rover hears them, finds them, talks
to them. A judge then changes the world (collapses a corridor, adds a second voice, starts a gas leak)
and the rover re-plans. Screen: sim view, live 3D map, camera with detections, decision log.

## Architecture
Four lanes, one folder each. The interfaces between them live in `coord/CONTRACT.md`.

| Lane | Folder | Owns |
|---|---|---|
| Sim and demo | `sim/` | World, rover model, sensors (real and emulated), noise, judge controls, demo screen |
| Perception | `perception/` | 3D SLAM, driveable map, semantic layer, person-candidate fusion |
| Autonomy | `autonomy/` | Mission manager, where to look next, actions per person, safety, re-planning, handover report |
| Voice | `voice/` | Speech in and out, triage dialogue, knock fallback, judge microphone path |

```
sim (sensors) --> perception (map, person candidates) --> autonomy (decisions) --> sim (motion, actions)
                                                              ^      |
                                     voice (triage result) ---+      +--> voice (say this / ask this)
```

## Lane status (each lane keeps its own block current)
### Sim and demo
- Done: / In progress: / Needs from other lanes:
### Perception
- Done: / In progress: / Needs from other lanes:
### Autonomy
- Done: / In progress: / Needs from other lanes:
### Voice
- Done: / In progress: / Needs from other lanes:

## Open decisions
- Simulator and middleware (for example Gazebo or Isaac Sim, ROS 2 or plain Python). Blocks every lane.
- SLAM package, and LiDAR-led, camera-led or combined.
- Speech stack (on-rover speech recognition and text to speech) and whether an LLM drives the dialogue.
- Which emulated sensors (suggested minimum: thermal).
- Building type, rover type, how many victims, gas hazard or not, which tasks to show (suggested:
  one supply delivery and one lead-out), and the name.
- Handover map format: point cloud, coloured mesh, or floor plan.

## Decisions log (append only, newest last; also post it on the board)
- Sat 7 Nov: robotics track, search and rescue rover in simulation, four lanes as above.
