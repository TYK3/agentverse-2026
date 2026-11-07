# Interfaces between lanes

Every boundary one lane calls on another goes here first, before code. Change it with a PR that
touches nothing else, and post the change on the board tagging the affected lanes.

Transport is **Open** until the simulator and middleware are picked (for example ROS 2 topics, or
plain Python with JSON messages). The shapes below are written as JSON so they can be kept either
way. Coordinates are metres in the map frame; times are seconds since the run started.

## Streams
| Name | Producer | Consumer | Shape |
|---|---|---|---|
| `sensors/lidar` | sim | perception | point cloud, 10 Hz |
| `sensors/rgbd` | sim | perception | colour and depth images, 10 Hz |
| `sensors/imu`, `sensors/odom` | sim | perception, autonomy | pose deltas, 50 Hz |
| `sensors/audio` | sim | voice, perception | audio chunks plus direction of arrival |
| `sensors/thermal`, `sensors/gas` | sim (emulated) | perception | readings with noise |
| `map/pose` | perception | autonomy, sim (screen) | `{"t":0.0,"x":0,"y":0,"z":0,"yaw":0}` |
| `map/grid` | perception | autonomy, sim (screen) | driveable map plus frontier cells |
| `map/semantic` | perception | autonomy, sim (screen) | list of objects below |
| `rover/cmd` | autonomy | sim | `{"v":0.0,"w":0.0}` or a goal `{"x":0,"y":0}` |
| `rover/action` | autonomy | sim | `{"action":"drop_supply"\|"place_beacon"\|"light_on"\|"push","target":"p1"}` |
| `voice/say` | autonomy | voice | `{"person":"p1","intent":"greet"\|"triage"\|"lead_out"\|"reassure"}` |
| `voice/triage` | voice | autonomy | `{"person":"p1","responsive":true,"hurt":true,"can_move":false,"others":1,"priority":"walking"\|"trapped_talking"\|"unresponsive"}` |
| `log/decision` | autonomy | sim (screen) | `{"t":0.0,"decision":"investigate voice","why":"voice heard left, 0.7"}` |
| `link/status` | sim | autonomy | `{"connected":false}` |

## Semantic objects
```json
{"id": "p1", "kind": "person", "x": 0, "y": 0, "z": 0,
 "confidence": 0.8, "clues": ["voice", "thermal"], "status": "possible" | "found"}
```
Kinds: `person`, `hazard` (with `"hazard": "gas" | "unstable" | "drop" | "fire"`), `door`, `supply`.
A person becomes `found` only with two different clues.

## Handover report (autonomy -> rescuers)
Map, each person with position, priority, condition and what the rover did, hazards, the safest
route to each person, timestamps. Format **Open**.

## Judge controls (sim)
`collapse_corridor`, `add_voice`, `start_gas_leak`, `drop_link`. Each changes the world mid-run.

## Fakes
Each lane ships a fake of what it provides, so nobody waits:
- sim: a recorded sensor stream or a scripted scene.
- perception: fixture `map/grid` and `map/semantic` files.
- autonomy: a scripted list of `rover/cmd` and `voice/say` messages.
- voice: text in, text out triage that returns `voice/triage`.
