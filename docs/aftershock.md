# AFTERSHOCK functional description

November 7, 2026 · @Anthony

This is the project spec. `coord/CONTEXT.md` summarises it and records decisions; `coord/CONTRACT.md`
holds the interfaces between lanes.

## Overview

AFTERSHOCK is a two-robot rescue system that maps a collapsed building, predicts where it may fail next, and delivers help only along routes it has checked. It is built as a simulation for the Agentverse 2026 Robotics track, using the Gemini models from the Builder Guide.

**The problem.** After an earthquake, rescuers cannot see inside a collapsed building, and a second collapse (an aftershock) can kill the people who go in. Sending a person or a heavy robot in blind wastes the first hours and adds risk.

**The idea.** Split the job in two. A small, light Scout rover goes in first and builds a live 3D map. The system then estimates which parts are unsafe, and only after that a stronger Responder robot is sent along the safest route to bring supplies, clear light obstacles and guide casualties.

**Who it is for.**

- Urban search-and-rescue teams deciding where it is safe to send people or machines.
- Operators who need to give commands by voice with their hands busy.
- Trapped casualties, who receive supplies and spoken guidance in their own language.

**What makes it different.** It does not just drive and map. Every decision is tied to something it perceived, a scene change forces a visible re-plan, and every route is checked by physics before a human approves anything risky.

## A run from start to finish

One scenario runs in the order below; the aftershock is the moment that proves the system adapts.

_(The flow diagram from the original doc is not reproduced here.)_ In outline: build the scene, the
Scout maps, casualties and hazards are estimated, the planner proposes a Responder route, physics
verifies it, a human approves risky moves, the Responder acts, the aftershock hits, the Scout re-scans,
the planner re-plans, and the handover report is drafted.

A route that fails the physics check goes back to the planner, risky moves wait for a human, and an aftershock sends the Scout back in before the Responder continues.

## Function 1: Scene builder (photo to simulation)

The scene builder turns a real photo of a tabletop collapsed building into a physics simulation, so the demo world comes from something the team physically built.

- **Input:** several photos of a cardboard or Lego model with fallen walls, gaps and rubble, taken with a phone or webcam.
- **What Gemini does:** `gemini-4-argon` reads the photos and writes the MuJoCo scene (walls, floors, rubble blocks, doorways) and a Three.js viewer for the browser.
- **Self-critique loop:** the agent renders the scene from several angles, compares screenshots with the photos, and fixes mismatches until they agree.
- **Output:** a runnable MuJoCo world with labelled blocks, plus a 3D view the operator can orbit.
- **Backup:** a hand-built version of the same scene, kept ready in case photo conversion is unreliable on the day.

## Function 2: Scout rover and live 3D mapping

The Scout is a small simulated rover whose only job is to see, and every cell of its map is labelled by how sure it is.

| Sensor (simulated) | What it gives the system |
| --- | --- |
| Ray-cast LiDAR | Distances to walls and rubble, used to build the 3D map |
| Camera | Images the model reads for gaps, doors, blocked paths and people |
| Thermal channel | Warm regions that may indicate a person |
| Acoustic channel | Direction of tapping or voices |

- **Map cell states:** *seen* (measured directly), *inferred* (guessed from nearby cells) and *unknown* (never observed). Only seen cells count as confirmed safe.
- **Behaviour:** the Scout explores toward unknown cells, and re-scans a cell it is unsure about before reporting it.
- **Reasoning log:** each move records the reading that caused it, so any decision can be traced back to a perception.
- **Future (real hardware):** a long-range low-power radio relay such as LoRa could keep the Scout connected deep inside; this is not part of the weekend build.

## Function 3: Casualty detection and aftershock hazard prediction

The system finds where people are and which parts of the building might fail next, and labels both as estimates.

**Casualty detection**

- Combines body pose in the camera image, a thermal signature and sound direction into one estimated position and a confidence.
- It does not use faces. Position is all the rescue needs, and avoiding faces removes a privacy and bias risk.
- Simulated vitals (for example breathing rate) appear in the report and are clearly marked as simulated.

**Hazard prediction**

- After mapping, the system flags blocks and walls that look load-bearing or poorly supported.
- A scripted aftershock then shakes the MuJoCo scene, and the physics shows which blocks actually move or fall.
- Result: each map cell is marked stable, at risk or collapsed, shown as a simulated estimate and not as structural engineering advice.

## Function 4: Planner and visible re-planning

One planner decides every move, checks it against physics, and shows its reasoning when the world changes.

1. **Plan.** `gemini-4-argon` reads the live map, the casualty position and the operator's goal, and proposes a route for the Responder.
2. **Verify.** The route is run through MuJoCo; if any cell on it is unstable, the route is rejected and a new one is proposed.
3. **Confidence gate.** The planner chooses one of three outcomes: act, re-look (send the Scout to scan again), or refer to a human. It never guesses silently.
4. **Re-plan on change.** When the aftershock or any other scene change happens, the old route fades on screen, the trigger is named, and the new route is drawn with a one-line reason.
5. **Log.** Each decision stores the perception, the model call, the physics result and the outcome.

## Function 5: Responder, supplies and the human gate

The Responder is the heavier robot that does physical work, and it moves only along routes the planner has verified.

- **Delivers supplies:** water, a first aid kit or a radio, placed near the casualty along the verified route.
- **Clears light obstacles:** with a simple gripper it can move small debris that blocks a path. It never moves anything it cannot judge safe.
- **Guides escape:** where a casualty can move, it indicates the safe exit route on the map and by voice.
- **Human gate:** any risky move (clearing an obstacle near a casualty, entering an at-risk cell) and any emergency call such as 999 need an explicit operator approval before it happens.
- **Scope note:** the original vision is a four-arm rover. For the weekend we build one Responder with one simple gripper, and describe more arms as the next step.

## Function 6: Voice, translation and first aid guidance

The operator and the casualty both interact by voice, and first aid stays as guidance for a human, not treatment by the robot.

- **Operator voice:** `gemini-3.8-live` takes spoken commands, including a change of mind mid-sentence ("send water to the left room, no, the back room"), and answers aloud with `gemini-3.8-flash-tts`.
- **Translation:** `gemini-3.5-live-translate-preview` lets a trapped person speak in their own language while the operator hears and answers in theirs.
- **First aid guidance:** the system reads out short, cited steps (for example how to check breathing or control bleeding) for the casualty or a bystander to follow. It does not diagnose, and anything medical needs a human to approve.
- **Emergency call:** the system prepares the report and location, but a human must confirm before any call is made.
- **Typed twin:** every voice command can also be typed, in case audio fails on the day.

## Function 7: Offline mode, edge budget and handover report

Inside a collapsed building the network will drop, so the system keeps working on the device and hands over a clear record at the end.

- **Offline planner:** when the connection is lost, a local Gemma 4 model (the E2B or E4B size) keeps planning routes. When the connection returns, `gemini-4-argon` re-checks what the local model decided.
- **Edge budget:** we state the device the planner must fit on (memory, model size, time per step) and show a live budget meter so judges can see it is respected.
- **Handover report:** at the end, `gemini-3.8-flash` drafts a structured report from the reasoning log: the map, casualty positions and confidence, hazards found, routes taken and re-plans, supplies delivered, and what a human approved.
- **Why it matters:** the next team arriving can read one page and know what is safe, what is not, and who is where.

## What the operator sees on screen

One browser screen shows the 3D map, the robots, the reasoning and the controls together, so the demo reads at a glance.

- **Centre:** the orbitable 3D map with seen, inferred and unknown cells, casualty markers and hazard colours.
- **Routes:** the current route in solid colour, the previous route faded after a re-plan.
- **Right panel:** reasoning log, confidence level and the model that made each decision.
- **Top bar:** the edge budget meter and an online or offline indicator.
- **Bottom bar:** voice or typed commands, approve and reject buttons for the human gate, and the handover report button.

## Built this weekend versus the full vision

The weekend build is one convincing scenario in simulation; everything else is described as the next step.

| Area | This weekend | Full vision |
| --- | --- | --- |
| Environment | One tabletop collapsed building, as a MuJoCo scene | Earthquake, tsunami and fire scenes, real buildings |
| Scout | Simulated rover with ray-cast LiDAR, camera, thermal and acoustic | Real rover with real sensors and a long-range radio relay |
| Responder | One robot with a simple gripper | Four-arm rover that clears heavier obstacles |
| Casualties | Detected by pose, thermal and sound; simulated vitals | Real vitals sensing and first aid assistance |
| Hazard prediction | Physics-based simulated estimate | Validated structural models with engineers |
| Offline | Gemma 4 local planner with a stated budget | Full on-robot autonomy |
| Safety | Human approval for risky moves and any 999 call | Same, plus certified emergenc… _(the source text was cut off here)_ |
