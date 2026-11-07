# AFTERSHOCK - five-minute pitch

Speaker copy. Target: five minutes including the live demonstration. These cues
are a proposed schedule; no rehearsal or live outcome is claimed. If an indicated
feature is still unavailable, use the honest limitation sentence rather than
describing a planned feature as something the audience just saw.

## 0:00-0:45 - Why this matters

After an earthquake, the first question is not just where someone is trapped.
It is whether the path to them will still be safe when help arrives. A second
collapse can turn a rescue route into a hazard.

AFTERSHOCK puts that uncertainty in the control loop. A light Scout gathers
evidence first. A heavier Responder receives a route after the system checks
what it knows, what remains uncertain and what the physics predicts. A person
stays in control of risky actions.

This prototype is for search-and-rescue operators. Today it is a simulation of
one collapsed building, not a certified tool for deployment in a real disaster.

## 0:45-1:30 - Perceive, decide, act

The Scout combines simulated LiDAR, camera, thermal and acoustic channels. Its
map distinguishes measured, inferred and unobserved cells. An inferred gap is
not permission to drive through it.

The local planner proposes a path through observed free cells. MuJoCo checks
whether an aftershock would make it unstable. The confidence gate acts, asks
the Scout to look again, or refers to a human. Every decision carries a reason.

## 1:30-2:30 - Demonstration

[Show the actual continuous take or live run. Point to perception and its matching
action. Let the operator approve a real pending request. Trigger the aftershock,
then have a teammate choose and inject a new obstacle during the run.]

Watch the old route. When the world changes, it becomes invalid. The Scout
must gather fresh evidence and the planner must verify a new route. The
teammate chooses the injected block's location during the run. A new
observation should cause the changed action, without a code edit.

[If integration is incomplete: "This recording currently uses the stand-ins
labelled on screen. We have not yet demonstrated that entire sequence with
all real lanes connected."]

## 2:30-3:15 - Architecture and autonomy

The components use a validated topic bus in one Python process. The console
receives maps, routes and reasoning over a WebSocket. Raw sensors remain local.

Core routing is local A-star. Gemini features add scene interpretation, route
review, voice, translation and reports. Offline goal reading uses gemma4:e2b
under Ollama; the safety decisions remain local rules. The offline lane reports
roughly 4.1 GB model memory and 1.8 to 2.8 seconds for warm goal reading on its
CPU target. Final full-system timing still needs measurement.

## 3:15-4:00 - Evidence and what it means

The message hub passed 42 transport and schema tests, plus five sim integration
checks. We also tested a real HTTP server and typed WebSocket round trip.

Our baseline harness scores safe success: reaching the casualty with zero
unsafe cells entered. Across 30 paired seeded grid layouts, naive routing
measured 25 safe successes and production routing 30. These are stand-in
results with oracle perception and no MuJoCo verification. They test the
measurement pipeline; real-sim evaluation remains pending.

## 4:00-5:00 - Safety, limits and next step

The critical failure is the second collapse. We revoke the old plan and require
a new verified route. Weak evidence means looking again or waiting for a human.

We do not identify faces. Casualties are positions and confidence estimates;
their vitals are labelled simulated. Hazard estimates are not structural
engineering advice. Medical guidance and emergency calls require a human.

Our scope is one simulated building and two robots. We still need real-lane
evaluation, the final device budget and a verified continuous demonstration.
Real rescue work would require hardware trials and domain validation.

The handover should tell an arriving team where someone may be, which routes
were checked, what changed and what a person approved. Help should move only
as far as its evidence supports.
