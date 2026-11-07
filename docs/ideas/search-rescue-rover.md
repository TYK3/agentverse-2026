# Search and rescue rover: sensors and decision making (ideation)

**Idea:** an autonomous rover enters a collapsed or smoke-filled building, scans it and builds a 3D map,
finds people, talks to them, does simple tasks to help, and comes out with a map of who is where. It
runs only in simulation, and no physical rover is needed.

This is ideation only: options, not decisions. **Open** marks a choice for the team.

## Why autonomy is essential here (the pitch hook)
Radio barely gets through rubble and concrete, so a rescue robot often **loses contact with its operator**
once it goes deep. It has to keep going and decide for itself. That fits the brief ("nothing to phone home
to") naturally. In the demo, the connection drops as it goes in, and it carries on alone.

## 1. Sensors

The simulator gives RGB and depth cameras, LiDAR, microphone, IMU and contact sensors directly. Thermal,
gas, CO2 and radar aren't built into most simulators, so they would be **emulated** from the simulation's
ground truth plus realistic noise. **Open:** which emulated sensors are worth it.

| Sensor | What it perceives | Why it matters | Priority |
|---|---|---|---|
| **3D LiDAR** | Walls, rubble, voids, distances | Builds the 3D map (SLAM), finds where it can drive | Must |
| **RGB-D camera** | Colour plus depth: people, doors, objects | Spotting people, colour 3D reconstruction, reading the scene | Must |
| **IMU plus wheel odometry** | Its own motion and tilt | Keeps localisation when dust or darkness blinds the cameras, and detects tipping on rubble | Must |
| **Microphone array** | Voices, knocking, direction of sound | Hears trapped people before it sees them, and listens to their answers | Must |
| **Speaker** (and lights) | (output) | Talks to people and gives signals | Must |
| **Bump and contact sensors** | Collisions, being stuck | Safe movement in tight rubble | Must |
| **Thermal camera** (emulated) | Body heat | Finds people under dust, in the dark, or partly buried | Should |
| **Gas sensor** (emulated) | Gas leaks, smoke, low oxygen | Danger to the robot's route and to people (links back to the gas idea) | Should |
| **CO2 sensor** (emulated) | Exhaled breath near voids | A real rescue technique for detecting someone breathing behind rubble | Could |
| **Radar** (emulated) | Breathing movement through debris | Finds unconscious people who make no sound | Could |
| **Downward or cliff sensor** | Drops and holes | Stops it driving into a void | Could |

**Suggested minimum set:** LiDAR, RGB-D camera, IMU, microphone plus speaker, contact sensors, and one
emulated "people" sensor (thermal). **Open.**

## 1b. 3D SLAM: how it builds the 3D environment

Yes, SLAM stays the core of the 3D environment. The rover builds the map and tracks where it is on it at
the same time, with no map given in advance.

- **Inputs:** LiDAR for shape and distance, RGB-D camera for colour and close-up depth, IMU and wheel
  odometry to keep track of itself when dust or darkness degrades the cameras.
- **What it builds:**
  1. a **3D geometry map** (voxels or a mesh) of rooms, rubble and voids;
  2. a **driveable map** derived from it (where the floor is flat enough and the gaps are wide enough);
  3. a **semantic layer** on top, with people, hazards, doors and supplies pinned in 3D as it finds them.
- **Loop closure:** when it comes back to a place it has seen, it corrects its accumulated drift, so the
  map stays accurate. That looks great on video, because the map visibly snaps into alignment.
- **It drives decisions:** the unexplored edges of the 3D map are where it looks next, and the map is what
  rescuers receive.
- **Adapting:** if a corridor collapses mid-run, the map updates and the route re-plans.
- **Use an existing SLAM package.** Don't write SLAM yourselves. The originality is in the semantic layer
  and the decisions on top. Add sensor noise so the map looks earned.
- **Open:** LiDAR-led, camera-led, or combined SLAM, and whether the handover map is shown as a point
  cloud, a coloured mesh, or a simple floor plan.

## 2. How it communicates with people

- **Talks and listens.** "Can you hear me? I'm a rescue robot. Help is coming." Speech recognition and
  speech generation run on the rover.
- **A fallback for people who can't speak:** "If you can hear me, knock twice." The microphone (or a
  vibration sensor) detects the knocks.
- **Quick triage questions:** "Are you hurt? Can you move? Is anyone else with you?" The answers set
  each person's priority.
- **Unconscious people:** it watches for breathing with camera, thermal or radar, and marks them as top
  priority.
- **Leading people out:** for people who can walk, it lights the way and says "follow my light".
- **To the rescue team:** it stores everything while out of contact and uploads it when back in range.
- **Open:** voice only, or a screen on the rover as well. Also, which languages.

## 3. Simple tasks it can do

- Drop a supply pack (water, a radio, a light, or a breathing mask) to a trapped person.
- Leave a beacon or marker so rescuers can find the person fast.
- Push aside light debris, or open a door.
- Lead someone who can walk out along a safe route.
- Mark dangers on the map (unstable areas, gas, fire).
- **Open:** which tasks to show. One delivery and one "lead out" is plenty for a weekend.

## 4. Decision making

Layered, from big picture to moment by moment. **Open:** how each layer is built. These are the decisions,
not the technology.

1. **Mission manager.** Decides what to do now: explore, investigate a clue, talk to a person, do a task,
   return. Each choice is driven by what it has perceived.
2. **Where to look next.** Picks the next place to explore from the unexplored edges of its 3D map,
   weighted towards where clues point (a voice from the left, heat behind a wall). It balances "cover the
   whole building" against "follow the strongest clue".
3. **Is that a person?** Combines clues (a voice, heat, a shape on camera, CO2) into a confidence for each
   possible person on the map. It needs two different clues before it declares someone found, which keeps
   false alarms down.
4. **Talking to them.** Picks the next question from the answers so far and assigns a priority: walking,
   trapped but talking, unresponsive.
5. **What to do for them.** Lead them out if they can walk; deliver supplies and leave a beacon if they're
   trapped; mark them top priority and keep searching if they're unresponsive. With several people, it
   decides who comes first.
6. **Staying safe and fail-safe.** Avoids unstable ground, drops and gas. Returns before the battery runs
   out. If unsure ("is that a person or a coat?"), it marks it as "possible person", doesn't overclaim,
   and moves on. Never reports an area as "safe".
7. **Re-planning.** When something changes (a corridor collapses, a new voice is heard, gas appears), it
   re-plans the route and priorities immediately, and logs why.

## 5. What it hands over
A 3D map with each person pinned and labelled by priority, their condition, what the rover did for them,
dangers, and the safest route to each one. Timestamped.

## 6. Demo ideas (open)
- **A judge is the trapped person.** They speak into a microphone as the victim behind the rubble. The
  rover hears them, finds them, and talks to them. This is live, unscripted and shows communication.
- **A judge changes the world:** collapses a corridor, adds a second voice, or starts a gas leak.
- **The connection drops** as it enters, and from then on it's on its own.
- Screen: simulator view, live 3D map building, camera with detections, and the decision log.

## 7. Novelty check
Search and rescue robots are a common theme, so plain "explore and map" won't stand out. What makes this
version different: **two-way talking and triage with victims, judge-as-victim interaction, and full
autonomy after losing contact**. Those should lead the pitch.

## 8. Open questions for the team
Building type (collapsed house, office, mine, tunnel); rover type (wheeled, tracked, legged, or a rover
with a scouting drone); which emulated sensors; what the supply pack holds; how many victims; whether
there's a gas hazard; and the name.
