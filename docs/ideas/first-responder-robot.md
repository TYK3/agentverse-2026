# First responder robot (robotics track version of the first aid agent)

**Short version:** the idea fits the robotics track far better than the biotech one. The simulated
version in the original pitch (a robot scans a scene for hazards, finds the casualty, fetches first aid
items and coaches a bystander) is close to the robotics brief word for word. The main change: the
**robot** becomes the agent, not a phone app, and its core decisions have to run on the robot itself.
Rough score against the robotics judging weights: **about 85/100**.

Anything marked **Open** is left for the team to decide together. Options are listed, but nothing is
chosen.

## 1. The robotics brief (from the AgentVerse slides)

"Give an agent a body." Build an embodied agent that **perceives** a simulated world through at least one
sensor, **decides** from what it senses (not a pre-scripted path), and **acts** (moves, navigates,
manipulates objects or communicates), "with nothing to phone home to".

- **Tools:** Isaac Sim is recommended (it needs an RTX GPU). MuJoCo, PyBullet, Gazebo or Webots also work.
  Sensors: RGB or depth camera, LiDAR, microphone, IMU, contact sensors. Get the stream running in the
  first hour. **Core decisions that depend on a remote service score lowest on autonomy.**
- **Submit:** a one-page technical summary PDF (user, problem, features, architecture, where each model
  runs with hardware and latency, limits, critical failure mode, safety); a **simulation video of up to one
  minute** in a single continuous take, showing perception next to actions and **one unscripted change**;
  and a 5 minute live pitch.
- **Judging:**

| Weight | Criterion | What a top score looks like |
|---|---|---|
| 25% | Perception-driven action | Every decision traces to what it perceived, and it corrects mid-run. |
| 25% | Adaptation to change | The scene changes mid-sequence and the agent visibly re-plans. |
| 15% | Operational autonomy | Runs within a stated edge-device budget and behaves sensibly when unsure. |
| 20% | Relevance and impact | A well-evidenced need, with the most critical failure mode handled on screen. |
| 15% | Ambition and technical quality | An original approach to a demanding problem, done to a high standard. |

## 2. The reworked idea

A robot reaches an incident before the ambulance does. It checks the scene for hazards, finds the
casualty, fetches the right kit, coaches whoever is nearby through first aid, watches the casualty for
change, and hands the paramedics a timestamped report when they arrive.

**Perceive.** Camera (plus depth or LiDAR) to build a hazard map (fire, smoke, spills, exposed cables,
traffic), find the casualty and their posture, and find useful items (first aid kit, defibrillator,
blanket). Microphone to hear the bystander. Synthetic casualty vital signs are a labelled stand-in for a
contact sensor or camera-based reading.

**Decide.** Is the route safe? Hold back, go around, or approach? What does the casualty need first
(bleeding, airway, breathing)? What to fetch, and in what order? When to escalate to "I'm not sure, keep
back and wait for paramedics"?

**Act.** Navigate to the casualty on a safe path, fetch and bring items, speak and show instructions to
the bystander one step at a time, keep a timed log, and produce the handover report.

### What carries over from the first aid idea
Scene safety before approach (now the robot's own go or no-go decision), the stepwise primary survey,
coaching the bystander, timed vitals labelled with their source, "I'm not sure" escalation, and the
handover report. Every instruction still cites published first aid guidance.

### What changes
- The robot is the agent, so the decisions are its own, made on board. A cloud LLM in the main loop
  would cost marks on autonomy.
- The "useful items" step becomes real manipulation and navigation, which is the robotics core.
- Photo-based injury suggestions shrink to what the robot can see and label with a confidence score.
- The 999 summary stays, but a human still places the call.

## 3. How it meets each judging criterion

- **Perception-driven action (25).** A live overlay shows each detection (hazard, casualty, kit) next to
  the action it triggered: "cable detected 1.2 m from path, re-routing". Every log line names its percept.
- **Adaptation to change (25).** This is the idea's strongest point, because emergencies change all the
  time. Candidate unscripted changes: a fire spreads across the planned route; a cable falls and starts
  sparking; someone moves the first aid kit; the casualty stops breathing, so the robot switches from
  bleeding care to CPR coaching and goes for the defibrillator. **Open:** which change to use for the
  single-take video, and whether a judge triggers it live during the pitch.
- **Operational autonomy (15).** All models run on board within a stated edge budget. When unsure (low
  confidence hazard, casualty not visible), it holds position, warns people to keep back and says so.
  **Open:** which edge device budget to state.
- **Relevance and impact (20).** The need: survival from cardiac arrest outside hospital in the UK is
  under 1 in 10, and every minute without CPR or a defibrillator lowers it. Bystanders often freeze or
  walk into danger. *Pull the exact figures from Resuscitation Council UK and NHS ambulance data before the
  pitch.* **The critical failure mode, shown on screen:** a hazard appears near the casualty after the
  robot has judged the scene clear. The robot stops, re-classifies the scene, tells the bystander to step
  back and re-plans.
- **Ambition and technical quality (15).** Hazard-aware navigation plus manipulation plus speech plus a
  live casualty model in one loop is demanding. Keeping the scope tight matters more than adding features.

## 4. Rough score

| Criterion | Weight | Score (1-5) | Why |
|---|---|---|---|
| Perception-driven action | 25 | 4 | Clear percept-to-action trace. Hazard detection quality is the risk. |
| Adaptation to change | 25 | 5 | Mid-run scene and casualty changes are natural, not contrived. |
| Operational autonomy | 15 | 4 | Fine if models are kept on board and the "unsure" behaviour is shown. |
| Relevance and impact | 20 | 4 | Strong, well-evidenced need. Needs real numbers in the pitch. |
| Ambition and technical quality | 15 | 4 | Ambitious. Quality depends on a tight scope. |
| **Total** | | | **about 85** |

## 5. Biggest risks

1. **Simulator setup eats the weekend.** Building a believable indoor incident scene, a robot that
   navigates and grasps, and hazard effects (fire, sparks) is a lot. Mitigation: the brief says get the
   stream running in the first hour, so make that the validation spike and start from a stock robot and
   scene.
2. **Hazard detection in simulation.** Off-the-shelf detectors won't know "live cable" or "spill". Options
   include training a small detector on simulator renders (synthetic data is cheap here) or reading
   ground truth from the simulator and adding noise. The second is easier but weaker on perception.
   **Open.**
3. **Grasping is hard.** Picking up a first aid kit reliably can take days. Fallbacks: push or tow items, a
   simple magnetic gripper, or "navigate to the item and guide the bystander to it". **Open.**
4. **Medical overclaiming.** Keep the safety rules: it never says a scene is "safe", only "no hazards
   detected", never diagnoses, and a human makes every call.

## 6. How we demonstrate it (simulation only, no hardware)

The track expects simulation only. Hardware isn't required, so it doesn't count against us.

- **Screen layout (video and live):** the simulator view in the main panel. Beside it: what the robot
  sees (camera with labelled detections, hazard map, planned path), a scrolling decision log where each
  line names the percept that caused it, and a small on-board compute and latency readout to show the
  edge budget.
- **The bystander is a real person.** A teammate (or a judge) speaks into a microphone as the bystander.
  The robot answers by voice and with on-screen steps, so the human part is live and unscripted.
- **A "chaos panel" for the unscripted change.** Buttons that change the scene mid-run: start a fire on
  the route, drop a sparking cable, move the kit, stop the casualty's breathing. In the live pitch a
  judge presses one and watches the robot re-plan. That covers the 25% for adaptation.
- **The one-minute video:** one continuous take of the full run with one change, recorded early as a
  backup in case the live stream fails on the day.
- **The ending:** the handover report appears as the "paramedic" arrives, timestamped and listing what
  was seen, measured and done.
- **SLAM map as the centrepiece (proposed):** the robot enters an unknown building and builds its map
  live. Hazards, the casualty and kit are pinned onto the map as it finds them (a semantic layer). When
  the scene changes, the map updates (the fire zone turns into a no-go area) and the path visibly
  re-routes. Use an existing SLAM package rather than writing one. The originality is in the hazard layer
  on top. **Open:** 2D LiDAR vs 3D camera map, and which package.
- **Open:** whether the live pitch runs the simulator live or plays the video with live narration, and
  whether a judge plays the bystander.

## 7. Open for ideation (team decides)

- **Setting:** a home, a train station, a factory floor, a university lab (chemical spill), a stadium,
  or a roadside.
- **Robot body:** wheeled, quadruped, humanoid, drone, or a **coordinated fleet** (one of the brief's
  suggested aims), for example a drone that scouts hazards while a ground robot fetches kit.
- **Who it helps:** an untrained bystander, the casualty themselves when conscious, or a remote ambulance
  dispatcher who watches its feed.
- **Which items it fetches and how:** grasp, push, carry in a bay, or guide a person to them.
- **How it talks:** voice only, a screen on the robot, projected prompts, or the bystander's phone.
- **The unscripted change** for the video and live pitch (see section 3).
- **The casualty model:** a simple scripted vital signs curve, a physiological model of bleeding and
  shock, or a teammate acting as the casualty in the simulator.
- **Simulator and models:** Isaac Sim vs a lighter simulator, and which on-board models (left until
  after the idea is picked, as agreed).
- **Extras:** practice mode for training first aiders, multiple casualties (triage), or night or smoke
  conditions.
- **Name and pitch story.**
