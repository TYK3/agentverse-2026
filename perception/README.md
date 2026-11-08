# perception lane: map, casualties, hazards

Spec: Functions 2 and 3 of `docs/aftershock.md`.

Owns: the live 3D map with every cell labelled seen, inferred or unknown (only seen counts as confirmed
safe); Scout exploration toward unknown cells and re-scans of uncertain ones; casualty detection that
fuses body pose, thermal and sound direction into a position and confidence (no faces; vitals marked
simulated); and hazard prediction that marks each cell stable, at risk or collapsed, checked against
what the aftershock actually moves.

Ships first: fixture files for the map, casualties and hazards, so the planner and console can start.

Owner: see the owner table in `AGENTS.md`. Only this lane's agent edits files here; others ask on the board.

## Hazards (T11, Z1: `perception/hazards.py`, `cloud.py`)

Hazards come only from the Scout's own scans. `scene/loaded` block poses and `world/change.moved_blocks`
are sim truth: perception does not read them (they stay in `perception/score.py` for tests and scoring).
`map/hazards` lists only `at_risk` and `collapsed` plan cells on k=0, always `estimate: true`, and is
published at 2 Hz when it changes (the planner replaces its list each time).

- **Before a shake: pile stability from depth points** (`sensors/scout.points`, Y9). A column whose
  points all float 0.15 m or more above floor the LiDAR saw open is an overhang. Stability is
  1 - (1.5 x overhang share + 1.0 x recent-motion share) over occupied columns within 0.2 m, and below
  0.5 is `at_risk`. That covers the slab and the wall it leans on. Without points nothing is predicted:
  the 2D LiDAR at 0.075 m cannot see a slab 0.3 m up.
- **At the shake** (`world/change`, either kind): the grid freezes its cells, and the at_risk prediction
  stays up ("not re-scanned yet") until the Scout measures those columns again. The Scout re-visits
  the predicted cells, nearest first, getting within 1 m.
- **After it: the LiDAR scan diff.** A cell well-seen free before and now returning 2+ hits means debris
  landed there: `collapsed`, with 0.15 m around it `at_risk`. A cell occupied before and now passed
  through by 3+ rays with no return means what stood there moved: `at_risk`. Each changed cell pulls
  the Scout over for a closer look.

On the backup scene (closed loop with ray-cast depth points standing in for Y9; the test world really
moves b8, b10 and b11), compared with sim truth:
- before the shake, at_risk vs b10+b8: precision 1.0, recall 0.69;
- after it, collapsed vs where they fell: precision 0.99 (the LiDAR sees fallen blocks' faces);
- cleared vs where b8 and b11 stood: precision 0.82, recall 0.97.

## Keep-out zones from sensed motion (L5, `perception/motion.py`)

A precaution from what the Scout saw move, not a collapse prediction. LiDAR and depth rays feed a
0.05 m voxel watch, one observation per voxel per frame (a return beats a pass). States are kept per
viewpoint (sensor origin binned to 0.1 m), because a corner that looks occupied from one spot can look
free from another. A voxel established as occupied (5 frames) that then reads free 3 frames running
has moved away; one established free that reads occupied 2 frames running, not touching an existing
surface, has had something land in it. Three such voxels within 0.3 m open a zone: every plan column
within 0.5 m is sent in `map/hazards` as `at_risk` with `exclusion: true`, and the planner never routes
through it. A zone is lifted only after 6 frames that re-measure its columns with no new motion; time
alone never lifts it. Motion is a change seen from the same place, so the Scout senses it while it
watches a pile. Scan changes while driving are the Z1 scan diff's job.

Backup scene closed loop: 90 s of exploring gives no zone. b10 sliding 0.15 m over 3 s while the
Scout watches from room 2 opens a zone over b10 (seen up to 0.47 m), and 6 s of still re-scans lift it.

## Injury triage and first-aid gate (Y3, `perception/triage.py`)

Assesses casualty condition and determines first-aid intervention:
- Fuses multi-modal observations: thermal signature, acoustic clues / sound level, camera posture check, and voice dialogue responses (via `voice.GUIDE.summary(cid)` or `casualty/answer`).
- Powered by `gemini-4-argon` through `coord/gem.py` (`lead_reasoning`) with `GEMINI_MODE=live`. In `GEMINI_MODE=off`, uses deterministic clinical triage rules.
- Triage priority levels: `immediate` (critical life-threat), `urgent` (stabilization needed), `delayed` (minor / stable), `unknown`.
- Matches injuries to Responder arm first-aid supply items: `water`, `first_aid_kit`, `radio`, `bandage`, `splint`, `thermal_blanket`.
- **First-Aid Gate & Human Card**:
  - High confidence (>= 0.8) and unambiguous condition: the existing automatic assessment accepts the supply choice and publishes `casualty/triage` for planner routing.
  - Unsure / ambiguous condition (< 0.8, conflicting clues, or severe multi-trauma): publishes `gate/decision` (`outcome="refer"`) and a needs-human triage card via `gate/request` (`kind="risky_move"`) with recommended supply options for operator approval.
  - Upon operator `gate/answer` (`approved=True`), publishes the accepted `casualty/triage {id,injuries,recommended_action}` and logs to `log/decision`. The planner waits for that choice, routes to the casualty, verifies physics, applies navigation/move gates and queues `move`, `place_supply`, `release` on the real route. Triage never publishes a physical arm command. The clinical gate's `route: none` grants no movement permission.
  - A pending or resolved review is not replayed by later casualty observations; an answer is consumed before any re-entrant bus publication. Attaching the singleton to a new bus starts a fresh run.
- Exposes `perception.triage.triage_summary(cid)` and `TRIAGE.summary(cid)` for integration with the Y6 remote paramedic report.

## Casualties (T10, `perception/casualties.py`)

`map/casualties` (contract shape, `vitals.simulated: true`) is published at 2 Hz when it changes, and is
`[]` while nobody is found. Clues, each scored 0..1, confidence = 0.4 thermal + 0.3 sound + 0.3 vision:

- thermal: the hottest region of the 16x12 grid above 0.6 gives a bearing (60 degree field of view);
- sound: the acoustic bearing, a 5-sample moving average; sound alone never creates an entry;
- position: thermal and loud sound rays from Scout poses at least 1 m apart, intersected (median),
  else the LiDAR range along the thermal bearing;
- vision (`pose` clue): the camera frame to `gemini-3.8-flash` through `coord/gem.py`, at most once a
  second and only when thermal or sound already suggests someone. With `GEMINI_MODE=off` it is skipped
  and marked as a stand-in (`gem.mark_stand_in("vision")`). Frames are never stored or forwarded.

On the T04 recording, c1 is found at (1.95, 0.98) (true (2.0, 1.0)), confidence 0.7, thermal + sound.
