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
