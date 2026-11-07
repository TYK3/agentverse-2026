# Gas leak marshal

## 1. The problem

**When toxic gas builds up in a confined or enclosed space, the people who go in to help become the next
victims.**

### What happens today
1. A worker collapses in a slurry pit, sewer, tank or lab store. The cause is a gas they can't see or, in
   the case of hydrogen sulphide at high concentration, can't smell, because it numbs the sense of smell.
2. A colleague sees them go down and goes in to pull them out. Within a breath or two, they collapse too.
3. Others nearby don't know where the gas is, which way it's moving or which exit is clear, so they leave
   by the route they know, which may run straight through the plume.
4. When the fire service arrives, nobody can say where the source is, how far the gas has spread or who
   is still inside. Someone in breathing apparatus has to go in and find out.

### Evidence (to verify before the pitch)
- NIOSH (US) is widely cited as finding that about **60% of confined space deaths are would-be
  rescuers**, from its alert on preventing deaths in confined spaces. Confirm the exact figure in the
  source.
- In the UK, farm slurry deaths regularly kill two or more people at once, with one going in after the
  other. One inquest found a farmworker [died trying to save a colleague](https://www.fwi.co.uk/business/business-management/health-and-safety/farmworker-died-trying-to-save-colleague-in-slurry-accident-inquest-told).
  Another case: [two men died in a Cheshire slurry tank](https://www.farminguk.com/news/two-men-die-following-slurry-tank-incident-on-cheshire-farm_69049.html).
  HSE has a dedicated guidance note on the dangers ([HSE AIS26](https://www.hse.gov.uk/PUBNS/ais26.pdf)).
- The UK exposure limit for hydrogen sulphide (HSE EH40) is 5 ppm averaged over 8 hours and 10 ppm over
  15 minutes. Slurry mixing can release hundreds of ppm, a level that can cause collapse almost at once.

### Why existing tools don't solve it
- **Fixed gas detectors** raise an alarm. They don't tell you where the source is, where the plume is
  heading, or which way is safe.
- **Handheld detectors** only measure where the person holding one is standing, so finding the source
  means walking through the gas.
- **Inspection robots with gas sensors** already exist on oil and gas sites, but they follow fixed patrol
  routes. They don't hunt for an unknown source live, and they don't guide people out.

### Problem statement
> **In a toxic gas emergency, nobody knows where the gas is or where it's going, so people walk into it,
> including the people trying to help. Rescuers die because finding the danger still means a human
> walking through it.**

### Who has the problem
- **Primary user:** the incident commander on scene (fire crew commander or site safety officer), who has
  to decide who goes where.
- **The people it protects:** workers and bystanders inside or near the space.
- **Open:** which setting the pitch leads with: farm slurry pit (the strongest UK evidence), sewer or
  water works, chemical or biotech lab, or industrial plant.

### Why a robot, and not sensors on the wall?
Judges will ask this, so the pitch must answer it head on.
- **Most of these places have no fixed sensors.** Farms, sewers, tanks, temporary sites and older
  buildings rarely have a detector network. The robot brings the sensing with it.
- **Fixed sensors can't pinpoint a source.** A few detectors on the wall tell you gas is present, not
  where it is coming from. Finding the source needs readings at many points inside the gas, which takes
  something that can move.
- **A sensor can't act.** The robot can shut off what's releasing the gas (a slurry mixer, a valve,
  a pump), open a vent, and **reach the casualty**: give them an escape mask, check whether they are
  breathing, or drag them out on a rescue sled. That last step is exactly what the colleague dies trying
  to do.
- **A body stops people better than a siren.** People ignore alarms. A robot standing in the doorway
  saying "don't go in, I'm getting them" is much harder to ignore.
- **Honest limit:** on a site with a dense fixed detector network, the robot adds less to *finding* the
  gas. Its value there is acting and reaching the casualty.
- **Open:** how far to take "reach the casualty" (check and report only, deliver a mask, or pull them
  out). Pulling them out is the strongest story and the hardest to build.

## 2. What success looks like
Each measure comes straight from the problem:

| Part of the problem | What we measure |
|---|---|
| Rescuers walking into the gas | Number of people who enter a zone above the short-term limit (target: zero) |
| Nobody knows where the source is | Time for the robot to locate the source, and its location error |
| People leave the wrong way | Each person's total gas dose on the way out, against the EH40 limits |
| Responders arrive blind | Whether the handover gives source, plume map, who is still inside, and safe positions |

**Baselines:** the same randomised scenarios run (a) with no robot, where people follow exit signs and one
"rescuer" goes in, and (b) with one person searching with a handheld detector. The pitch shows one chart
of the robot against both baselines.

## 3. The solution: an autonomous rover (simulated, no hardware)

**The rover is the project.** Everything is shown in simulation, so we don't need a physical rover. The
brief only asks for a simulated embodied agent. The rover gets a mission, goes in alone, and makes every
decision on board with no operator and no remote service.

### The rover's mission, start to finish
1. **Enter an unknown space.** No map is given. It builds one live with SLAM from LiDAR and camera.
2. **Hunt the source.** Using a gas sensor that reads only where it stands, plus a wind sensor, it keeps a
   live probability map of where the source could be and chooses where to sample next. Plumes are patchy
   and shift, so it can't just climb the strongest reading.
3. **Find the casualty.** It detects the collapsed person with its camera and checks them (are they
   moving, roughly breathing).
4. **Act.** It shuts off the source (a mixer, a valve or a pump) or opens a vent, then deals with the
   casualty. **Open:** check and report only, deliver a mask, or drag them clear on a sled.
5. **Guard the entrance.** If a person appears heading in, it warns them and holds the doorway.
6. **Come back and hand over.** It returns with the map: source, gas concentrations, casualty position
   and condition, and the safe zones.

### Autonomy, which is what the judges score
- **Every decision is made on board**, within a stated compute budget (an edge GPU class device). Each
  model's latency is listed in the one-page summary. **Open:** which device to state.
- **Every action traces to a percept.** A live log reads like "gas 38 ppm rising to the north-east, wind
  from the south, sampling the north-east corner next".
- **It re-plans by itself** when the world changes: a door opens and the plume moves, a path is blocked,
  the casualty moves, or a second source appears.
- **It fails safe when unsure.** If the gas sensor fails, the battery runs low, or it can't localise the
  source within a time limit, it marks the area as no-go, retreats and reports why. It never reports
  "safe".
- **No human in the loop during the run.** Humans only see the handover at the end.

## 4. The demo: judges test the rover's autonomy

The rover is the star. Judges don't drive it. They change its world and watch it cope.

1. **Hide the leak.** A judge places the source anywhere on the floor plan before the run, so the run
   can't be rehearsed.
2. **Change the world mid-run** from a small control panel: open a door (the airflow shifts and the plume
   moves), drop an obstacle in its path, add a second leak, move the casualty, or kill its gas sensor to
   test the fail-safe.
3. **Watch it think.** Split screen: the simulator view; its live SLAM map with the gas probability map
   on top; the camera with detections; and the decision log.
4. **Receive the handover.** A judge acting as fire commander gets the map and report at the end.
5. **The one-minute video:** one continuous take of the full mission with one unscripted change
   (the door opening).

**Optional, open:** simulated people inside, so the rover also has to stop a would-be rescuer. It adds
drama but also build time, so add it only once the core mission works.

## 5. Fit with the robotics judging

| Criterion | Weight | How | Score |
|---|---|---|---|
| Perception-driven action | 25 | People found by camera and gas found by sensor, with every move traced to a reading. | 5 |
| Adaptation to change | 25 | Unknown leak position, unknown map, and judges changing the world mid-run. | 5 |
| Operational autonomy | 15 | Runs on board within a stated budget, and fails safe when unsure. | 4 |
| Relevance and impact | 20 | A sourced problem, a named user, the critical failure shown, measured against baselines. | 5 |
| Ambition and quality | 15 | Live source search combined with crowd guidance is rare and demanding. | 4 |
| **Total** | | | **about 93** |

## 6. Risks
1. **The gas model:** keep it 2D, a floor plan with airflow and diffusion, not full 3D fluid simulation.
2. **Simulator setup:** get the rover driving and streaming in the first hour, as the brief advises.
3. **Scope.** Build order: drive plus SLAM, then gas plus source search, then the fail-safe, then acting
   (shut-off), then the casualty, then the control panel, and finally optional people.

## 7. Still open for the team
Setting, gas type, rover type (wheeled or tracked; a drone scout is an optional extra), how it signals to people,
the simulator and on-board models, and the name.
