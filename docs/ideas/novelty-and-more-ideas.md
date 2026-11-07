# Novelty check and more robotics ideas

## 1. How original is the first responder robot?

**Honestly, not very: about 2 out of 5.** Search and rescue robots are among the most common robotics
hackathon themes, and the real world is ahead of it. Drones have already delivered defibrillators to real
cardiac arrests in Sweden, and DARPA ran a whole underground rescue robot challenge. A judge's first
thought will be "seen it".

The parts that are fresher are the human parts: a robot that **coaches untrained people** instead of
doing the rescue itself, and the **handover report**. Novelty lies there, not in the robot driving to
the casualty.

## 2. Ways to make the first aid idea more original

- **Incident commander robot.** The robot can't do CPR, but it can run the crowd. It perceives several
  bystanders and gives each one a role ("you, call 999", "you, fetch the defibrillator", "you, press
  here"). Then it watches whether they do it, using pose estimation to check CPR depth and rate, and
  corrects them. A robot directing humans is much rarer than a robot doing the task itself.
- **Find the casualty by sound.** A microphone array hears a call for help or breathing behind a wall,
  and the robot locates it by sound before it can see it.
- **Smell the hazard.** Add a gas sensor so "scene safety" includes an invisible leak the camera can't
  see (see idea B below).

## 3. New ideas

Scored roughly against the robotics weights (perception 25, adaptation 25, autonomy 15, relevance 20,
ambition 15). N = novelty out of 5.

| | Idea | One line | N | Score |
|---|---|---|---|---|
| **A** | **Incident commander** | First aid reworked as above: a robot that directs and corrects a crowd of untrained helpers. | 4 | ~88 |
| **B** | **Sniffer** | A robot finds an invisible gas leak by smell, tracking a plume that shifts with the airflow, before people enter. | 5 | ~89 |
| **C** | **Night shift lab robot** | It patrols a biology lab overnight: a freezer fails, so it triages which samples to rescue first. | 4 | ~85 |
| **D** | **Ask, don't guess** | A home robot that knows when it's unsure, points and asks one question, and learns from the answer immediately. | 4 | ~84 |
| **E** | **No server fleet** | Robots share a busy corridor or hospital with no central controller, agreeing on right of way by signals alone. | 3 | ~82 |
| **F** | **Guide quadruped** | A robot guide dog for a blind traveller in a station. Crowds surge and lifts break. | 3 | ~83 |

### A. Incident commander (the strongest way to keep your idea)
- **Perceive:** camera plus pose estimation on several people and the casualty; microphone for speech.
- **Decide:** assign roles from who is present and what they're doing; re-assign if someone freezes or
  leaves.
- **Act:** speak, point, light up the route to the defibrillator, fetch kit.
- **Adaptation:** a helper walks off mid-CPR, so the robot re-assigns the role; the casualty starts
  breathing, so it switches everyone to the recovery position.
- **Critical failure:** wrong CPR technique. It perceives poor depth or rate and corrects it on screen.
- **Open:** how to simulate the helpers (real teammates via motion capture or webcam, or simulated
  people), and how many.

### B. Sniffer (most original)
- **Perceive:** a simulated gas sensor (only one point reading at a time), wind sensor, camera, LiDAR.
- **Decide:** gas plumes are patchy and shift with the airflow, so you can't just follow the gradient.
  The robot keeps a live probability map of where the source could be and chooses where to sniff next.
- **Act:** navigate, close a valve or shut a door, and mark the no-go area for responders.
- **Adaptation:** someone opens a window and the wind direction flips, so the map and route change
  visibly. This makes a striking video.
- **Relevance:** gas leaks in buildings, labs and plants, where sending people in first is the danger.
  It ties back to your "check the scene is safe" idea.
- **Risk:** the plume simulation. A simple 2D airflow and diffusion model is enough. **Open:** how
  realistic to make it.

### C. Night shift lab robot
Keeps the biotech link. Fridges, freezers and incubators fail at night and years of samples are lost.
The robot patrols, hears alarms, reads displays, and when a freezer fails it decides which racks to move
into a backup freezer first, by labelled value. Adaptation: a second failure, or a blocked corridor.
**Open:** what it can manipulate in the simulator.

### D. Ask, don't guess
It targets the brief's "learning on the fly" and the "behaves sensibly when unsure" criterion directly.
A tidy-up or fetch robot that, when unsure ("is this mug rubbish or yours?"), stops, points and asks one
short question, then remembers the answer and applies it to similar objects for the rest of the run.
The judge answers live, so it's very interactive. **Open:** the setting (home, ward, office).

### E. No server fleet
It takes "nothing to phone home to" literally. Several robots with no central controller share a
narrow hospital corridor and negotiate passage with lights or movement alone. Adaptation: one robot
breaks down in the corridor. It is technically deep, but harder to explain in 5 minutes.

### F. Guide quadruped
It has a strong human need and a natural failure mode (it leads someone into danger). Robot guide dogs
already exist in research, so novelty is middling.

## 4. The problem each top idea solves

*These figures are widely cited but not yet checked. Verify each against its source before the pitch.*

**A. Incident commander.**
- **User:** a crowd of untrained bystanders at a cardiac arrest in a public place (station, shopping
  centre, office), before the ambulance arrives.
- **Problem:** people freeze, everyone assumes someone else has acted, CPR is too shallow or slow, and
  the nearby defibrillator stays on the wall. Survival from cardiac arrest outside hospital in the UK is
  under 1 in 10 and falls by roughly 10% for each minute without CPR or defibrillation (source to check:
  Resuscitation Council UK). A defibrillator is rarely used before the ambulance arrives.
- **Problem statement:** *"The help is in the room. The defibrillator and the people are there, but
  nobody is coordinating them. The robot turns a frozen crowd into a team within a minute."*

**B. Sniffer.**
- **User:** a first responder or a site safety officer at a building, lab, sewer or farm with a
  suspected gas leak or toxic atmosphere.
- **Problem:** you can't see gas, and the people who rush in to help become victims. Most deaths in
  confined spaces are often cited as would-be rescuers (source to check: NIOSH). Hydrogen sulphide in
  slurry pits and sewers, and carbon monoxide or natural gas indoors, are the usual causes. Finding the
  source with a handheld detector means a person walking through the danger zone.
- **Problem statement:** *"The first person into a toxic room shouldn't be a person. The robot goes in,
  finds the source by smell, shuts it off if it can, and tells responders exactly where it's safe to
  stand."*
- **Open:** which setting to pitch (farm slurry pit, sewer, chemical lab, home gas leak). Each has a
  different user and a different evidence base.

## 5. Recommendation

- **To keep the first aid story:** go with **A, Incident commander**. It's the same mission with a
  twist judges won't have seen.
- **For maximum novelty:** go with **B, Sniffer**. It's the most unusual, gives the strongest
  "the scene changes and it re-plans" moment, and it can still be pitched as a first responder tool.
- **Open:** combine them. Sniffer finds the leak and makes the area safe, then hands over to the
  commander role once people arrive. That's a lot to build in a weekend, though.

## 6. Incident commander in other scenarios

The core pattern carries over: the robot **perceives people** (where they are, what they're doing,
who needs help), **gives each one a role or a direction**, **checks they did it**, and **re-assigns**
when someone freezes, leaves, or the scene changes. Any setting with a confused crowd and a ticking
clock fits.

| | Scenario | Problem it solves | The mid-run change | N | Score |
|---|---|---|---|---|---|
| **1** | **Gas leak marshal** (Sniffer plus commander) | People in a lab or factory don't know where the gas is or which way to leave. The robot sniffs out the plume and steers each person out of it. | The wind flips, the plume moves, and the robot re-routes everyone. | 5 | ~90 |
| **2** | **Evacuation marshal** | In fires, people head for the door they came in through, crowd one exit and leave less mobile people behind. | Smoke blocks the main exit mid-evacuation. | 4 | ~88 |
| **3** | **Crowd crush prevention** | Crushes at concerts and stations (Hillsborough, Itaewon, Astroworld) build up within minutes from density nobody on the ground can see. | A gate closes and density spikes at one point. | 4 | ~87 |
| **4** | **Road collision scene** | Secondary crashes hit people standing at an accident. The robot places warnings, keeps bystanders off the road, and assigns roles. | A car approaches too fast, or a second casualty is found. | 3 | ~83 |
| **5** | **Mass casualty triage** | At a major incident, a handful of responders face dozens of casualties. The robot tags them by priority and puts the walking wounded to work helping. | A "minor" casualty deteriorates. | 3 | ~84 |

**Recommendation: 1, Gas leak marshal.** It merges the two strongest ideas (perceiving gas *and*
people), has the most original sensing, and gives the best re-planning moment on video. **2,
Evacuation marshal,** is the safer build, since crowd simulation is well understood and the problem
needs no explaining.

**Open:** the setting, how many people, and whether the people in the simulation are simulated agents
or teammates driving avatars live (the second makes the unscripted change real).
