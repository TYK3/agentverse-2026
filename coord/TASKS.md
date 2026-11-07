# AFTERSHOCK task list (one GitHub issue per `## T..` heading)

Source of truth for the build. Spec: `docs/aftershock.md`. Interfaces: `coord/CONTRACT.md`. Rules: `AGENTS.md`.
Every task below becomes one issue. `{N}` in a body is replaced by the issue number when the issue is created.

Working rules every task repeats in short form:
- Branch from fresh main: `git fetch origin && git switch -c {N}-<slug> origin/main`
- Stage only your own lane's files by name (never `git add -A`). Small commits.
- PR body starts with `Closes #{N}`; fill in the PR template (Why / Contract changes / Tested with exact commands).
- Before you push: `git fetch origin && git rebase origin/main`
- When something others depend on merges, post on the board: PR link, exact interface, how to run it.
- A "done" post must link the PR, say how to run it, and say what was tested and what was not.

Proposals for the lead to log in `coord/CONTEXT.md` (decisions log) before lanes start; the tasks assume them:
1. **Transport:** one Python process, an in-process bus plus one WebSocket gateway (`coord/hub.py`, FastAPI). Every message is `{"topic": "<name from CONTRACT.md>", "data": {...}}`. The browser console connects to `ws://localhost:8000/ws`.
2. **Autonomy:** the brief scores core decisions that depend on a remote service lowest. So the route decision (A* over verified cells, the confidence gate, the human gate) runs locally in Python. `gemini-4-argon` is used for scene building, for explaining decisions, and as the online double-check; Gemma 4 runs locally for goal interpretation and the offline planner.
3. **Languages:** Python 3.11+ for sim, perception, planner, voice, hub. TypeScript + Three.js (Vite) for the console.
4. **Frame:** metres, z up, grid resolution 0.05 m, cell = `[i, j, k]` = floor(position / 0.05).

---

## How we use Gemini (read this before building)

Claude Code and Codex build everything. Gemini is never used to build the code. Gemini agents are welcome on the team board like any other agent: they can join, report in, chat, review and suggest under the rules in `AGENTS.md`. Inside the product, Gemini only runs for jobs that need it or were made for it. Antigravity is kept for at most two named jobs (T27). This saves credits (the temporary hackathon account is rate-limited and heavy use can get a team disqualified) and keeps the build fast.

1. **Building:** Claude Code and Codex write all code and tests. Do not use Gemini to build: no Gemini coding agent, no AI Studio Build, no Antigravity for building. Gemini agents are not locked out of anything else: they join the board, post `[<person>'s <agent>]` messages, read unread posts, report status, discuss, review and suggest, exactly as `AGENTS.md` says for any agent. In each coding agent install the official Gemini skills once so it writes current Gemini 4 and Interactions API code instead of retired parameters: `npx skills add google-gemini/gemini-skills --skill gemini-api-dev` and `npx skills add google-gemini/gemini-skills --skill gemini-live-api-dev`.
2. **Runtime Gemini jobs (the only ones):**

| Job | Model ID | Task | Why Gemini |
|---|---|---|---|
| Photos to MuJoCo scene, with a render-and-critique loop | `gemini-4-argon` | T07 | Multimodal generation plus self-critique; the guide's robotics blueprint |
| Operator voice with mid-sentence changes | `gemini-3.8-live` | T21 | Real-time two-way voice; Claude and Codex do not do live audio |
| Spoken guidance | `gemini-3.8-flash-tts` | T22 | Speech output |
| Casualty and operator translation | `gemini-3.5-live-translate-preview` | T22 | Streaming speech translation |
| Read the Scout camera frame for a person | `gemini-3.8-flash` | T10 | Vision on a sensor frame; at most 1 call per second, only when thermal or sound already hints at a casualty |
| Online review of a physics-verified route | `gemini-4-argon` | T13 | One call per verified route, 5 s timeout, never blocks the decision |
| Handover report text | `gemini-3.8-flash` | T16 | One call per run; a plain template is the fallback |
| Offline planner | `gemma-4` E2B or E4B, local | T15 | Runs on the laptop, uses no Gemini credits |

3. **Never Gemini:** the hub, the map, A* routing, hazard rules, the physics check, the confidence gate, the human gate, the budget meter, the console, the eval harness. These run locally (the brief scores remote-dependent core decisions lowest).
4. **One door:** every Gemini call made by the product code goes through `coord/gem.py` (T26). This is about the code we ship, not about Gemini agents chatting or reporting on the board: model IDs in one place, a mode switch, a call cap, retry on 429 and 503, the key from the environment only.
5. **Modes:** `GEMINI_MODE=off` (default while building: every Gemini feature uses a labelled local stand-in), `replay` (reuse a cached answer, or call once and cache it), `live` (real calls). The console shows a badge `GEMINI: OFF / REPLAY / LIVE` and lists any stand-in in use.
6. **The demo is `live` only, with no stand-ins.** The guide forbids mocked screens or hardcoded JSON that pretend to call Gemini. A stand-in is for development and tests and must say so on screen and in logs.
7. **Merge order:** each lane builds and merges against fakes with `GEMINI_MODE=off`. At integration (T23) one machine with the key switches to `live`, and the Gemini feature owners fix what breaks. Only that machine and the feature owners need the key; nobody commits it.
8. **Keys and quota:** each person may use their own key from the temporary account (AI Studio, "Import project", key at aistudio.google.com/api-keys). Do not commit a key (all keys in the project can be disabled). On a 429, raise the spend cap moderately at aistudio.google.com/spend. The account is deleted soon after the event, so copy out anything you need.

---

## T01 | shared | Environment, API key and first Gemini call
Depends on: nothing. Everyone does this in hour one. Owner: lead (shared files), everyone runs it.

**What:** one shared virtual environment recipe, the Gemini skills installed in every coding agent, a key that is never committed, and proof that each model ID answers.

**How:**
```
git switch -c {N}-env origin/main
python3 -m venv .venv && source .venv/bin/activate        # Git Bash on Windows: source .venv/Scripts/activate
printf 'mujoco\nnumpy\ngoogle-genai>=2.3.0\nfastapi\nuvicorn[standard]\nwebsockets\npydantic>=2\npillow\npsutil\nsounddevice\npython-dotenv\npytest\nruff\n' > requirements.txt
pip install -r requirements.txt
python tools/mujoco_check.py
npx skills add google-gemini/gemini-skills --skill gemini-api-dev
npx skills add google-gemini/gemini-skills --skill gemini-live-api-dev
grep -qxF '.env' .gitignore || echo '.env' >> .gitignore
cp /dev/null .env.example && echo 'GEMINI_API_KEY=' >> .env.example
```
Each person puts their own key in `.env` (never commit it). Create `tools/gemini_ping.py`:
```python
import os, sys
from dotenv import load_dotenv
from google import genai
load_dotenv()
client = genai.Client()  # reads GEMINI_API_KEY
for model in sys.argv[1:] or ["gemini-4-argon", "gemini-3.8-flash"]:
    r = client.interactions.create(model=model, input="Reply with the single word: ready",
                                   generation_config={"thinking_level": "low"})
    print(model, "->", r.output_text)
```
Run `python tools/gemini_ping.py gemini-4-argon gemini-3.8-flash`. This is the only place a bare `genai.Client()` is used; everything else goes through `coord/gem.py` (T26). If `gemini-4-argon` fails, post the exact error on the board and tag @TYK3; do not switch models silently.

**Done when:** `pytest -q` runs (even with 0 tests), `python tools/mujoco_check.py` passes on every teammate's laptop, `gemini_ping.py` prints an answer for `gemini-4-argon` and `gemini-3.8-flash` (one person is enough; do not have everyone spend calls), `.env` is ignored, the two skills are installed in your coding agent.

---

## T02 | shared | Message hub (bus + WebSocket gateway) and message schemas
Depends on: T01. Owner: lead. Blocks every lane, so merge it first.

**What:** `coord/hub.py` (bus + gateway), `coord/messages.py` (pydantic models for every row of `coord/CONTRACT.md`), `coord/fixtures/` (JSON examples).

**How:** create `coord/hub.py`:
```python
import asyncio, json
from collections import defaultdict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

class Bus:
    def __init__(self): self.subs = defaultdict(list); self.clients = set(); self.history = []
    def subscribe(self, topic, fn): self.subs[topic].append(fn)          # fn(data: dict) may be sync or async
    async def publish(self, topic, data):
        msg = {"topic": topic, "data": data}; self.history.append(msg)
        for fn in self.subs[topic]:
            r = fn(data)
            if asyncio.iscoroutine(r): await r
        for ws in list(self.clients):
            try: await ws.send_text(json.dumps(msg))
            except Exception: self.clients.discard(ws)

bus = Bus()
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])

@app.websocket("/ws")
async def ws(ws: WebSocket):
    await ws.accept(); bus.clients.add(ws)
    for m in bus.history[-200:]: await ws.send_text(json.dumps(m))        # late joiners catch up
    try:
        while True:
            m = json.loads(await ws.receive_text())
            await bus.publish(m["topic"], m["data"])                      # console sends operator/command, gate/answer
    except WebSocketDisconnect: bus.clients.discard(ws)
```
`coord/messages.py`: one pydantic `BaseModel` per message in CONTRACT.md plus `TOPICS: dict[str, type[BaseModel]]`. Add `publish_checked(topic, data)` that validates against `TOPICS[topic]` before `bus.publish`. Put one valid example per topic in `coord/fixtures/<topic with / replaced by __>.json` (for example `map__cells.json`). Run with `uvicorn coord.hub:app --port 8000 --reload`. Lanes plug in by exposing `async def start(bus)` in their package and `coord/hub.py` calls each lane's `start` on startup (add an `on_event("startup")` hook listing `sim.start`, `perception.start`, `planner.start`, `voice.start`; a missing lane is skipped with `try/except ImportError`).

**Test:** `coord/tests/test_hub.py` publishes every fixture through `publish_checked` and asserts a WebSocket test client (`fastapi.testclient.TestClient(app).websocket_connect("/ws")`) receives it.

**Done when:** `pytest coord/tests -q` is green, `curl -i http://localhost:8000/docs` returns 200, and the board has a post with the module path and the envelope format. Log the transport decision in `coord/CONTEXT.md`.

---

## T03 | sim | Hand-built backup scene (MJCF) and scene/loaded
Depends on: T01, T02. Lane: `sim/`.

**What:** the demo world that always works: a floor, a 3-room collapsed building with a doorway, rubble blocks, one casualty marker, a mocap ground plate (for the aftershock), two named cameras.

**How:** `mkdir -p sim/scenes && $EDITOR sim/scenes/backup.xml`. Skeleton:
```xml
<mujoco model="aftershock_backup">
  <option timestep="0.002" gravity="0 0 -9.81"/>
  <worldbody>
    <body name="ground" mocap="true" pos="0 0 0">
      <geom name="floor" type="box" size="3 3 0.05" pos="0 0 -0.05" rgba="0.5 0.5 0.5 1"/>
    </body>
    <body name="b1" pos="1.0 0.0 0.5"><freejoint/><geom name="b1_g" type="box" size="0.05 0.6 0.5" mass="8" rgba="0.8 0.7 0.5 1"/></body>
    <!-- add walls b2..b8 so three rooms exist, a doorway 0.5 m wide, 4 to 6 rubble blocks b9.. leaning on walls -->
    <body name="casualty_c1" pos="2.0 1.0 0.1"><geom name="c1_g" type="capsule" size="0.12 0.3" contype="0" conaffinity="0" rgba="1 0.3 0.3 1"/></body>
    <camera name="scout_cam" pos="0 0 0.2" euler="90 0 0"/>
    <camera name="overview" pos="0 -4 3" xyaxes="1 0 0 0 0.6 0.8"/>
  </worldbody>
</mujoco>
```
Keep every wall and rubble block a separate body named `b<number>` with a `label` comment (wall, rubble). Then `sim/scene.py`:
```python
import mujoco, pathlib
def load(path="sim/scenes/backup.xml"):
    m = mujoco.MjModel.from_xml_path(path); d = mujoco.MjData(m); mujoco.mj_forward(m, d); return m, d
def blocks(m, d):
    out = []
    for i in range(m.nbody):
        n = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i)
        if n and n.startswith("b"): out.append({"id": n, "label": "wall", "pos": d.xpos[i].tolist(), "size": m.geom_size[m.body_geomadr[i]].tolist()})
    return out
```
`sim/__init__.py` exposes `async def start(bus)` that loads the scene and publishes `scene/loaded` with `{"scene":"backup","blocks":[...]}`. Check by eye: `python -m mujoco.viewer --mjcf=sim/scenes/backup.xml`.

**Done when:** the viewer shows the scene stable for 10 s with no blocks drifting, `scene/loaded` validates, and the board has a post with the scene path. Perception and console use this scene first.

---

## T04 | sim | Scout rover: model, driving and sensor stream
Depends on: T03. Lane: `sim/`.

**What:** a small Scout (box body with two drive joints or a planar mocap-driven body), ray-cast LiDAR, camera frames, a synthetic thermal grid and a synthetic acoustic bearing, all published as `sensors/scout` at 10 Hz. Get this running in the first hour: it unblocks perception.

**How:** drive the Scout kinematically (fast, deterministic): make it a mocap body `scout` and move it with `d.mocap_pos[k]` toward the target from `scout/goto`, speed 0.3 m/s, refusing to pass through occupied space (ray check forward 0.15 m). Sensors in `sim/sensors.py`:
```python
import mujoco, numpy as np
def lidar(m, d, origin, n=360, max_range=6.0):
    ranges = np.full(n, max_range); geomid = np.zeros(1, dtype=np.int32)
    for k in range(n):
        a = 2*np.pi*k/n; vec = np.array([np.cos(a), np.sin(a), 0.0])
        dist = mujoco.mj_ray(m, d, origin, vec, None, 1, m.body("scout").id, geomid)
        if dist >= 0: ranges[k] = min(dist, max_range)
    return ranges
def camera(m, d, renderer, name="scout_cam"):
    renderer.update_scene(d, camera=name); return renderer.render()    # np.uint8 [H,W,3]
```
Create the renderer once: `renderer = mujoco.Renderer(m, height=240, width=320)`. On a headless Linux box set `MUJOCO_GL=egl` first. Thermal: a 16x12 float grid, 0.1 background and a Gaussian blob of 0.9 around the casualty if it is within 4 m and in line of sight (one `mj_ray` from the Scout to the casualty that reaches it). Acoustic: `{"bearing": degrees to the casualty relative to the Scout heading, "level": 0..1 falling with distance and with walls in between}`, plus 0.05 noise. The camera frame is sent as a small JPEG base64 only to perception (`sensors/scout` is not forwarded to the browser: filter it in the gateway, since frames are large).

Also publish `scout/pose` inside `sensors/scout` as `{"pose":{"pos":[x,y,z],"yaw":rad}}`. Record 60 s of the stream to `sim/recordings/scout_backup.jsonl` (images omitted) as the fake for perception.

**Done when:** `python -m sim.record --seconds 60` writes the file, the Scout explores when `scout/goto` messages arrive (test by publishing one with `tools/` or a `curl`-style WebSocket send), and `sensors/scout` appears on the bus at about 10 Hz.

---

## T05 | sim | Aftershock event and physics route check
Depends on: T03. Lane: `sim/`. This is the demo moment; test it hard.

**What:** `trigger_aftershock()` shakes the ground plate and publishes `world/change`; `verify_route(cells)` answers `route/verified` using physics.

**How:** shake: ground is a mocap body, so each step set `d.mocap_pos[0] = [A*np.sin(2*np.pi*f*t), 0, 0]` with A=0.03 m and f=4 Hz for 2.0 s, then 1.0 s settle. Compare every block's start and end pose.
```python
def aftershock_effects(m, d, seconds=3.0, thresh=0.05):
    sim = mujoco.MjData(m); mujoco.mj_copyData(sim, m, d)               # never shake the live world when verifying
    start = {n: sim.xpos[m.body(n).id].copy() for n in block_names(m)}
    for step in range(int(seconds / m.opt.timestep)):
        t = step * m.opt.timestep
        sim.mocap_pos[0] = [0.03*np.sin(2*np.pi*4*t) if t < 2.0 else 0.0, 0, 0]
        mujoco.mj_step(m, sim)
    return [n for n, p in start.items() if np.linalg.norm(sim.xpos[m.body(n).id] - p) > thresh]
```
`unstable cells` = every grid cell within 0.10 m of the box of each moved block. `verify_route(cells)`: run `aftershock_effects` on a copy, return `{"id", "ok": not any(c in unstable for c in cells), "unstable_cells": [...], "detail": "block b7 falls"}`. `trigger_aftershock()` runs the shake on the LIVE data over real time (so the viewer shows it) and publishes `world/change` `{"kind":"aftershock","t":<s>,"moved_blocks":[...]}` and nothing else. Subscribe `route/proposed` and publish `route/verified` within 1 s (cache the unstable set; recompute after every `world/change`).

Also add the unscripted-change hook the brief requires: `sim/inject.py` exposes `POST /inject {"kind":"block_added","pos":[x,y,z]}` on the hub (a new rubble block dropped into the route), which publishes `world/change` with `"kind":"block_added"`.

**Test:** `pytest sim/tests/test_aftershock.py`: a block leaning on a wall in the backup scene moves, a block on flat floor does not, `verify_route` rejects a route through the moved block's cells, and a second call with the same inputs gives the same answer (set seeds, no random).

**Done when:** `python -m sim.demo_aftershock` shows the shake in the viewer and prints the moved blocks; `route/verified` returns both ok and not-ok in tests.

---

## T06 | sim | Responder model, motion and supply actions
Depends on: T03, T05. Lane: `sim/`.

**What:** a heavier Responder (bigger box, one simple gripper) that follows `route/proposed` cells and handles `responder/action`: `move`, `place_supply`, `grip`, `release`.

**How:** another mocap body `responder` moving cell-to-cell at 0.2 m/s. Supplies are small free bodies `water`, `first_aid_kit`, `radio` carried by welding to the Responder: in the MJCF add `<equality><weld name="carry" body1="responder" body2="water" active="false"/></equality>`; `grip` sets `m.eq_active[eq_id] = 1`, `release` sets it to 0 and lets the object fall. `grip` of an obstacle only succeeds for blocks with mass < 2 kg (light debris). Refuse anything else and say so by publishing `log/decision` with `outcome: "refused"` (the contract has no separate result message). Refuse any action not preceded by a matching approved `gate/answer` when the route is flagged risky (the check lives in planner T14; sim trusts the planner but asserts it in tests).

**Done when:** a scripted sequence (move to casualty, place water, grip a 1 kg block, release) works in `python -m sim.demo_responder`, and the Responder never moves through a block (collision rays checked each step).

---

## T07 | sim | Photo-to-scene builder with self-critique loop
Depends on: T01, T03, T26. Lane: `sim/`. The "wow" feature; the backup scene (T03) must already work so this can fail safely. Gemini job: `gemini-4-argon` via `coord/gem.py`. Do NOT use Antigravity here: render locally with `mujoco.Renderer`, which is free and faster. Build and test with `GEMINI_MODE=replay` so repeated test runs cost nothing.

**What:** `python -m sim.scene_builder photos/*.jpg` sends the tabletop photos to `gemini-4-argon`, gets back an MJCF scene, renders it from three angles, shows the renders back to the model, and repeats up to 4 times.

**How:**
1. `mkdir -p sim/photos sim/generated`; take 3 to 5 photos of the cardboard/Lego model from different angles, put them in `sim/photos/` (these are our own photos; no people in them).
2. Prompt (store in `sim/prompts/scene.md`): "You are given photos of a tabletop model of a collapsed building. Output ONLY a MuJoCo MJCF file. Use the same conventions as `sim/scenes/backup.xml` (paste it): metres, z up, a mocap body named `ground`, every wall or rubble block a separate body named `b<number>`, a body `casualty_c1`, cameras `scout_cam` and `overview`. Keep every block's size and mass plausible for a 1:20 model scaled to a 6 m by 6 m room."
3. Call: `gem.ask("lead_reasoning", input=[...], thinking="medium", feature="scene")`, which wraps `client.interactions.create(model="gemini-4-argon", input=..., generation_config={"thinking_level": "medium"})` and returns `interaction.output_text`. Upload each photo with `client.files.upload(file=path)` as the guide does for video and pass the returned file in `input`; the guide shows `{"type": "video", "uri": file.uri}` for video, so confirm the exact image item shape with the installed `gemini-api-dev` skill rather than guessing. If the scene is large, use `background=True` with `max_output_tokens` above 65536 as in the guide and poll with `client.interactions.get(id=...)`.
4. Validate: `mujoco.MjModel.from_xml_string(xml)` must load, and `python -c` a 3 s settle must keep blocks within 0.05 m. On error, send the error text back to the model (max 4 rounds).
5. Critique: render `overview` plus two more cameras with `mujoco.Renderer`, save PNGs to `sim/generated/iter<k>_<cam>.png`, send photos + renders to the model: "List mismatches between the photos and these renders, then output the corrected MJCF."
6. Write the winner to `sim/generated/photo_scene.xml`. If any step fails after 4 rounds, publish `scene/loaded` with `"scene":"backup"` and log why. Never block the demo on this. With `GEMINI_MODE=off` this task only loads the backup scene and says so on screen.

**Done when:** two photo sets produce a loadable scene; the critique loop's iteration images are saved; failure falls back to the backup scene cleanly. Save the best iteration images for the pitch.

---

## T08 | perception | Live occupancy map with seen / inferred / unknown cells
Depends on: T02, T04 (use `sim/recordings/scout_backup.jsonl` until T04 merges). Lane: `perception/`.

**What:** turn `sensors/scout` into `map/cells` at 0.05 m, with states `seen`, `inferred`, `unknown`.

**How:** `perception/grid.py`: a dict `{(i,j,k): {"state", "occupied", "hits"}}`. For each LiDAR ray from the Scout pose: walk the ray in 0.05 m steps, mark each traversed cell `seen` + `occupied: false`, and the hit cell `seen` + `occupied: true`. Inference: after each update, any `unknown` cell with at least 5 of its 6 face neighbours `seen` and occupied becomes `inferred` + `occupied: true` (a wall's hidden interior); free space is never inferred. Publish `map/cells` at 2 Hz as only the changed cells since the last message, plus a full snapshot every 5 s (`"res": 0.05`). Only z = 0 and 1 layers are needed for the demo; keep k small.

**Test:** `pytest perception/tests/test_grid.py` with a synthetic square room: all wall cells `seen` after one full sweep, a cell behind a wall stays `unknown`, and a re-scan never turns `seen` back to `unknown`.

**Done when:** replaying `sim/recordings/scout_backup.jsonl` through `python -m perception.replay` produces a map whose seen cell count rises monotonically, and the console (T18) shows it.

---

## T09 | perception | Scout exploration (frontier driving) and re-look
Depends on: T08. Lane: `perception/`.

**What:** the Scout decides where to go next from the map, not from a script.

**How:** every 1 s, find frontier cells: `seen` free cells with at least one `unknown` neighbour. Pick the nearest by BFS path length that is not in an `at_risk` or `collapsed` hazard cell; publish `scout/goto {"target":[x,y,z],"reason":"frontier at cell [i,j,k], 14 unknown neighbours"}`. When the planner asks for a re-look (`gate/decision` with `outcome: "relook"` and a cell in its reason, or a `scout/goto` from the planner), obey it first. After a `world/change`, mark every cell within 0.5 m of `moved_blocks` as `unknown` again, so the Scout re-scans them (this is what makes the re-plan honest).

**Done when:** on the backup scene the Scout covers every reachable room with no scripted path, and after `trigger_aftershock()` it returns to re-scan the moved area within 20 s. Record the reason strings: they feed the reasoning log.

---

## T10 | perception | Casualty detection by pose, thermal and sound (no faces)
Depends on: T04, T08, T26. Lane: `perception/`. Gemini job: `gemini-3.8-flash` via `coord/gem.py`, vision only. Build with `GEMINI_MODE=off`: thermal and sound alone must already work, and the vision clue is skipped and flagged as a stand-in.

**What:** fuse three clues into `map/casualties`.

**How:** thermal: connected region of the thermal grid above 0.6, converted to a world bearing and range using the Scout pose and the camera field of view. Sound: the bearing from the acoustic channel; keep a 5-sample moving average. Vision: send the camera frame to `gemini-3.8-flash` with the prompt "Is there a person-shaped figure lying or sitting in this image? Answer JSON only: {\"person\": bool, \"bbox\": [x,y,w,h], \"posture\": \"lying|sitting|standing|unknown\"}. Do not describe faces." Gate the call: at most 1 per second, only when thermal OR sound already suggests a casualty (this keeps cost and latency down). Fuse by triangulation: the intersection of the thermal ray and the sound ray from two Scout poses at least 1 m apart; confidence = 0.4*thermal + 0.3*sound + 0.3*vision (each in 0..1), `clues` lists the ones present. Output exactly the `map/casualties` shape in `coord/CONTRACT.md`, with `vitals.simulated: true`. Never store or send image crops; the camera frame is dropped after the call.

**Done when:** on the backup scene `c1` is found with confidence at least 0.7 from at least two clues, a fake with only thermal gives a lower confidence, and a scene with no casualty yields no entry. Add `perception/tests/test_casualties.py`.

---

## T11 | perception | Hazard prediction (stable / at_risk / collapsed)
Depends on: T05, T08. Lane: `perception/`.

**What:** label map cells before and after the aftershock, always marked `estimate: true`.

**How:** before: a block is `at_risk` if (a) it is a wall taller than it is wide whose base footprint is under 50% supported by cells beneath it, or (b) a rubble block rests with its centre of mass beyond its support edge (centre of mass xy outside the convex hull of its contact points with the block below). Use `sim` helper `contacts(m, d)` (add it to the sim lane's public API; ask on the board) or the block list from `scene/loaded` and simple AABB overlap. After `world/change`: cells of `moved_blocks` become `collapsed`, cells within 0.15 m of them become `at_risk`, everything else keeps its label. Publish `map/hazards` with `"why"` strings that name the block ("unsupported wall b7").

**Done when:** in the backup scene b7 (the leaning wall) is `at_risk` before the shake and `collapsed` after; hazard labels are shown as estimates; `perception/tests/test_hazards.py` passes.

---

## T12 | planner | Local route planner over verified cells
Depends on: T02, T08 fixtures (`coord/fixtures/map__cells.json`). Lane: `planner/`.

**What:** the on-device decision core: A* from the Responder to a goal next to a casualty through cells that are `seen`, free, and not `at_risk` or `collapsed`.

**How:** `planner/route.py`: 3D grid A* (use z=0 layer, 8-connected, cost = distance + 5 for cells within 0.15 m of an occupied cell to keep clearance). Inputs: latest `map/cells`, `map/hazards`, goal cell. If no path exists using only `seen` cells, return `{"status":"no_verified_route","needs":"re-look","cells":[...frontier near the goal...]}`. Publish `route/proposed {"id":"r<k>","robot":"responder","cells":[...],"goal":"deliver water to c1","model":"local-astar"}`. The `model` field is `"gemini-4-argon"` only when the online model reviewed the route (T13), and `"gemma-4-local"` when the offline planner chose the goal (T15).

**Test:** `planner/tests/test_route.py` with fixtures: finds the shortest path in an open room, goes around an `at_risk` cell, returns `no_verified_route` when the doorway is `collapsed`, never uses `inferred` or `unknown` cells.

**Done when:** `pytest planner -q` passes and, fed the fixtures, `python -m planner.fake_run` prints a route.

---

## T13 | planner | Verify loop, confidence gate, re-plan on change, reasoning log
Depends on: T12, T05, T26. Lane: `planner/`. Everything in this loop runs locally. The only Gemini call is the optional online review through `coord/gem.py`; with `GEMINI_MODE=off` it is skipped and the log says `online_review: stand-in (gemini off)`.

**What:** the loop that makes the demo: propose, physics-verify, gate, act, and re-plan visibly on `world/change`.

**How:** state machine in `planner/loop.py`: `IDLE -> PROPOSED -> VERIFIED -> GATED -> EXECUTING`. On `route/verified ok:false`, add `unstable_cells` to the hazard set and re-plan (max 3 times, then `refer`). Confidence gate: `confidence = min(casualty.confidence, fraction of route cells that are seen)`; `>= 0.8` `act`, `0.5 to 0.8` `relook` (publish `scout/goto` to the weakest cell), `< 0.5` `refer` (publish `gate/request` kind `risky_move` so a human decides). Publish `gate/decision` every time. On `world/change`: stop the Responder, publish `log/decision {"perception":"aftershock moved b7","outcome":"replanning",...}`, wait for the Scout re-scan (map version increases), then propose a new route and publish it with a one-line `reason`. Online double-check: after a verified route, call `gem.ask("lead_reasoning", ...)` (`gemini-4-argon`) with the map summary, hazards and the route; ask for a JSON `{"agree":bool,"why":"one line"}`; if it disagrees, escalate to `refer`. If the call fails or times out (5 s), continue locally and note `"online_review":"skipped"` in the log. Every decision writes `log/decision {"t","perception","model","physics","outcome","reason"}`.

**Done when:** a scripted run on fixtures produces propose, verify fail, re-plan, verify ok, and a `world/change` triggers a new route with a `reason`; `planner/tests/test_loop.py` covers each gate band.

---

## T14 | planner | Human gate and Responder task execution
Depends on: T13, T06. Lane: `planner/`.

**What:** nothing risky happens without an approval.

**How:** a move is risky if the route crosses an `at_risk` cell, the action is `grip` on an obstacle, or the intent is an emergency call. Publish `gate/request {"id":"g<k>","kind":"risky_move|enter_at_risk|emergency_call","summary":"...","route":"r3"}` and wait for `gate/answer {"id","approved"}` with a 60 s timeout (timeout means refused). Only after `approved: true` publish `responder/action` messages in order: `move` along the route, `place_supply` with the `item`, `release`. For `emergency_call` only prepare the message and show it; never place a call from code (no phone or network call exists in this repo).

**Done when:** tests prove no `responder/action` of a risky kind is emitted without an approval, a denial leaves the Responder idle and logs it, and a timeout counts as refused.

---

## T15 | planner | Offline mode with local Gemma 4 and the edge budget meter
Depends on: T13. Lane: `planner/`.

**What:** when `status/link` says `online:false`, the same loop continues with a local model and shows its budget.

**How:** step 1, the lead logs the decision: which device and runtime. Find out what really exists before choosing: check the Gemma 4 model cards for E2B/E4B artifacts and a runtime that loads them locally (for example Ollama, llama.cpp or Hugging Face transformers); run the runtime's own list or pull command and record the exact tag in `coord/CONTEXT.md`. Do not guess a tag. Step 2: `planner/local_llm.py` with `ask(prompt: str) -> str` that calls the local runtime; used only for goal interpretation ("send water to the back room" to a goal cell) and an explanation line, never for the safety decision. Step 3: `planner/budget.py` measures `psutil.Process().memory_info().rss / 1e6` and the ms per planner step and publishes `status/budget {"device":"<the stated device>","mem_mb":..,"model":"gemma-4-e2b","ms_per_step":..,"limit":{"mem_mb":..,"ms_per_step":..}}` every second; limits live in `planner/budget.json`. Step 4: `tools/link_toggle.py` publishes `status/link` `{"online":false}` (the demo switch; also a keyboard shortcut in the console, T20). Step 5: when `online` returns, re-check the offline-chosen route with `gem.ask("lead_reasoning", ...)` and publish a `log/decision` with the verdict.

**Done when:** with the network switched off in the code path (`online:false`), a full propose/verify/gate cycle completes using only local compute, the budget meter is within its limit on the demo laptop, and the model field of `route/proposed` is `local-astar` or `gemma-4-local`.

---

## T16 | planner | Handover report
Depends on: T13, T14, T26. Lane: `planner/`. Gemini job: `gemini-3.8-flash` via `coord/gem.py`, one call per run. Build and test the template renderer first with `GEMINI_MODE=off`.

**What:** one page the next team can read.

**How:** `planner/report.py` collects: final map stats, casualties with confidence and clues, hazards before and after, every route and re-plan reason, supplies delivered, every approval with who/when. Ask `gemini-3.8-flash` for a structured JSON (sections: summary, casualties, hazards, actions, approvals, open risks) and render Markdown; if the call fails, render the same report with a plain template. Mark simulated vitals and estimates in the text. Publish `report/handover` with the JSON and the Markdown; also write `reports/handover_<timestamp>.md` (gitignore `reports/`).

**Done when:** after a fixture run the report lists the aftershock re-plan and every approval, contains the words "simulated" and "estimate" where relevant, and has no image or face data.

---

## T17 | console | Vite + Three.js scaffold with live WebSocket client
Depends on: T02. Lane: `console/`.

**How:**
```
cd console
npm create vite@latest . -- --template vanilla-ts
npm i three && npm i -D @types/three
npm run dev -- --port 5173
```
`console/src/bus.ts`: connect to `ws://localhost:8000/ws`, reconnect every 2 s, `on(topic, fn)` and `send(topic, data)`. Fake mode: `?fake=1` replays `coord/fixtures/*.json` (copy them to `console/public/fixtures/`) so you never wait for another lane. Layout from the spec: centre canvas, right panel, top bar, bottom bar (empty containers with ids).

**Done when:** `npm run build` passes, the page connects to the hub, and `?fake=1` logs every fixture to the console.

---

## T18 | console | 3D map, robots, casualties and hazard colours
Depends on: T17. Lane: `console/`.

**How:** `three` `InstancedMesh` of 0.05 m cubes, one instance per `map/cells` cell: `seen` solid, `inferred` translucent (`opacity 0.35`), `unknown` not drawn (or very faint wireframe). Occupied cells grey, free cells hidden. Hazards tint: stable none, `at_risk` amber, `collapsed` red, labelled as estimates in a legend. Casualty markers: a sphere plus a label `c1 (0.82, estimate)`; vitals text with `(simulated)`. Robots: two meshes from `sensors/scout` pose and `responder/action` moves. `OrbitControls` from `three/examples/jsm/controls/OrbitControls.js`. Batch updates once per animation frame.

**Done when:** `?fake=1` shows a coloured map with casualty and hazards, orbit works, and 100k cells render at 30 fps or better on a laptop.

---

## T19 | console | Routes, the visible re-plan and the world-change banner
Depends on: T18. Lane: `console/`. This is the key demo visual.

**How:** draw `route/proposed` cells as a `Line2`/`TubeGeometry` in solid blue. When a new `route/proposed` arrives, fade the old line to 20% opacity over 1 s and keep it for 8 s labelled "previous route". On `world/change`, show a banner "Aftershock detected: b7 moved. Re-scanning" and flash the moved blocks red; when the next route arrives, show its `reason` text. `route/verified ok:false` draws the unstable cells in red with the `detail`.

**Done when:** replaying `world/change` then a new route in fake mode shows the faded old route, the banner and the reason, with no page reload.

---

## T20 | console | Panels: reasoning log, confidence, budget, link, commands, approvals, report
Depends on: T17. Lane: `console/`.

**How:** right panel: scrolling list from `log/decision` (time, model, one-line reason; colour by outcome) and the latest `gate/decision` with a confidence bar. Top bar: the Gemini badge from `status/gemini` (`GEMINI: LIVE`, `REPLAY` or `OFF`, with the stand-in list in a tooltip; see T26), `status/budget` as a meter (mem and ms/step against limits, red when over) and an Online/Offline pill from `status/link`; key `o` sends `status/link` toggle for the demo. Bottom bar: text input that sends `operator/command {"text","source":"typed"}`; a mic button placeholder (voice lane wires it); modal for each `gate/request` with Approve and Reject sending `gate/answer`; button "Handover report" opens the `report/handover` Markdown in a panel. Simulated or estimate items always carry a visible badge.

**Done when:** in fake mode every panel updates from fixtures, approve/reject sends the right message (check in the Network tab), and `npm run build` passes.

---

## T21 | voice | Operator voice commands with mid-sentence changes
Depends on: T02, T14 (fixtures meanwhile), T26. Lane: `voice/`. Gemini job: `gemini-3.8-live`, the one thing Claude and Codex cannot do. Install the `gemini-live-api-dev` skill in your coding agent first. Build the typed twin and the intent parser with `GEMINI_MODE=off`; the live session is switched on at integration. No faked live calls in the demo.

**How:** `voice/operator.py`: open a `gemini-3.8-live` session with `google-genai` (read the Builder Guide and the SDK's live session docs for the exact connect call; do not guess its shape), stream microphone audio (`sounddevice` 16 kHz mono) into it, and ask the model to return the FINAL intent only, as JSON `{"goal":"deliver","item":"water","place":"back room"}`, resolving self-corrections ("left room, no, the back room"). Publish `operator/command {"text":"send water to the back room","source":"voice"}`. A typed twin: `voice/typed.py` reads stdin lines and publishes the same message; the console's typed bar (T20) already does this. Provide push-to-talk (hold space) so noise cannot trigger it.

**Done when:** three spoken commands, one with a change of mind, produce three correct `operator/command` messages; with no microphone the typed twin works; a transcript is logged.

---

## T22 | voice | Spoken guidance (TTS), casualty translation and cited first aid
Depends on: T21, T26. Lane: `voice/`. Gemini jobs: `gemini-3.8-flash-tts` and `gemini-3.5-live-translate-preview`. With `GEMINI_MODE=off` the console shows the `say` text and translation shows `[translation unavailable: gemini off]`.

**How:** `voice/speak.py`: subscribe `say`; synthesise with `gemini-3.8-flash-tts` and play with `sounddevice`; if TTS fails, show text only (the console already shows `say`). `voice/translate.py`: for `say` with `to:"casualty"`, translate with `gemini-3.5-live-translate-preview` into the casualty's language (the demo language is an open decision: choose one and log it), and translate the casualty's reply back to the operator's language. First aid: `voice/firstaid.json` holds 5 to 8 short steps (check breathing, control bleeding, keep warm, do not move the neck unless in danger...). Each step MUST carry a `source` URL you opened and read (for example a national first aid body's page); no step without a source. The system reads them out as guidance for a human, never as a diagnosis. Emergency call: prepare the text (location cell, casualty clues, estimated vitals marked simulated) and publish `gate/request kind:"emergency_call"` through the planner; voice never calls anyone.

**Done when:** a `say` message is spoken, a casualty line round-trips through translation in the chosen language, and every first aid step has a source field checked in a test.

---

## T23 | shared | Integration runner with one unscripted change
Depends on: T05, T13, T18, T20, T26 (and the Gemini features T07, T10, T16, T21, T22 for the live run). Owner: lead.

**How:** `tools/run_demo.sh` starts everything: `uvicorn coord.hub:app --port 8000` and `(cd console && npm run dev -- --port 5173)`. `tools/run_scenario.py --seed 7` drives the scripted path: scene load, Scout explores, casualty found, route proposed, verified, human approves (auto-approve flag only for tests), the Responder starts, the aftershock fires, re-plan, delivery, report. Add `POST /inject` (T05) as the UNSCRIPTED change the brief requires: during the one-minute take, a teammate drops a block into the route while the system is running; the planner must re-plan without a code change. Log the whole run to `runs/<seed>.jsonl` (gitignored).

Run the final rehearsals with `GEMINI_MODE=live`. `tools/run_scenario.py --require-live` must fail if any stand-in is active (read it from the `status/gemini` message in T26). This is the merge-up step: the Gemini feature owners (T07, T10, T13, T16, T21, T22) fix what breaks when the real calls go on.

**Done when:** `bash tools/run_demo.sh` and `GEMINI_MODE=live python tools/run_scenario.py --seed 7 --require-live` complete end to end on a clean clone, three times in a row, and an injected block changes the route.

---

## T24 | shared | Baseline harness: naive planner versus AFTERSHOCK over seeded runs
Depends on: T23. Owner: lead or the planner lane.

**How:** `tools/eval.py --runs 30`: seeds 0..29 vary rubble positions and the casualty cell (same scene, parameterised). Two planners: `naive` (shortest path through all known free cells, ignores hazards and the physics check) and `aftershock` (full system). Metrics per run: reached casualty (bool), unsafe cells entered (cells that become `collapsed` while the Responder is in them or enters one), time to casualty, number of re-plans, human approvals. Output `eval/results.csv` and a bar chart `eval/safe_success.png` with matplotlib (add to requirements). Report SAFE success (reached and entered no unsafe cell), not raw success. Do not report a number that was not measured.

**Done when:** `python tools/eval.py --runs 30` finishes in under 15 minutes and the CSV plus chart exist; put the two headline numbers in the one-page summary.

---

## T25 | shared | Submission pack: one-page PDF, one-minute video, pitch, README
Depends on: T23, T24. Owner: lead. Brief: one-page technical summary PDF, a simulation video of up to one minute in one continuous take with perception next to actions and one unscripted change, and a 5-minute live pitch. Deadlines are open: confirm the Sunday submission time with the organisers and post it on the board.

**How:** PDF sections (from the brief): user, problem, features, architecture, where each model runs (with hardware and latency from the budget meter), limits, the critical failure mode (second collapse), safety (human gate, no faces, simulated labels). Video: record with OBS or the OS recorder at 1080p, one take, console visible beside the viewer; keep a spare take. README must name the problem, the exact model IDs used (`gemini-4-argon`, `gemini-3.8-flash`, `gemini-3.8-live`, `gemini-3.8-flash-tts`, `gemini-3.5-live-translate-preview`, `gemma-4-...` with the exact tag) and the verification loop (propose, physics check, gate, human approval). Pitch: 5 minutes; rehearse twice; keep a screen recording as the backup. Freeze features at least 2 hours before submission and tag the demo commit: `git tag demo-final && git push origin demo-final`.

**Done when:** the PDF, the video file and the README are in the submission, all three open on a different machine, and the demo commit is tagged.

---

## T26 | shared | The one Gemini door: `coord/gem.py`, modes, call cap, badge
Depends on: T01. Owner: lead. Merge this right after T02: every Gemini task depends on it.

**What:** one module all Gemini calls pass through, so we build with Claude and Codex at zero Gemini cost and still show real calls in the demo.

**How:** `coord/gem.py`:
```python
import os, time, json, hashlib, pathlib, threading
MODEL_IDS = {   # copied from the Builder Guide
    "lead_reasoning": "gemini-4-argon", "managed_sandbox": "antigravity-preview-09-2026",
    "fast_subagent": "gemini-3.8-flash", "fast_router": "gemini-3.5-flash-lite",
    "live_voice_vision": "gemini-3.8-live", "live_translate": "gemini-3.5-live-translate-preview",
    "tts_studio": "gemini-3.8-flash-tts", "open_model": "gemma-4-31b-it"}
MODE = os.environ.get("GEMINI_MODE", "off")              # off | replay | live
CAP = int(os.environ.get("GEMINI_CAP_PER_HOUR", "300"))   # stay far below "thousands of requests"
CACHE = pathlib.Path(".gem_cache"); _calls, _lock, _client = [], threading.Lock(), None
stand_ins = set()                                        # features that ran without Gemini, for the badge
class GeminiOff(Exception): pass

def _c():
    global _client
    if _client is None:
        from google import genai; _client = genai.Client()   # key from GEMINI_API_KEY, never hardcoded
    return _client

def ask(model_key, input, thinking="medium", feature="?", **config):
    """Returns the model text. Raises GeminiOff in off mode: the caller uses its own stand-in and calls mark_stand_in(feature)."""
    if MODE == "off": raise GeminiOff(feature)
    key = hashlib.sha256(json.dumps([model_key, thinking, str(input)], sort_keys=True).encode()).hexdigest()
    f = CACHE / f"{key}.txt"
    if MODE == "replay" and f.exists(): return f.read_text()
    with _lock:
        now = time.time(); _calls[:] = [t for t in _calls if now - t < 3600]
        if len(_calls) >= CAP: raise RuntimeError("gemini call cap reached; raise GEMINI_CAP_PER_HOUR on purpose")
        _calls.append(now)
    for attempt in range(3):                              # 429 and 503 only, short backoff
        try:
            r = _c().interactions.create(model=MODEL_IDS[model_key], input=input,
                    generation_config={"thinking_level": thinking, **config})
            text = r.output_text
            CACHE.mkdir(exist_ok=True); f.write_text(text)
            return text
        except Exception as e:
            if attempt == 2 or not any(c in str(e) for c in ("429", "503")): raise
            time.sleep(2 ** attempt)

def mark_stand_in(feature): stand_ins.add(feature)
def status(): return {"mode": MODE, "calls_last_hour": len(_calls), "stand_ins": sorted(stand_ins)}
```
Add `.gem_cache/` to `.gitignore`. Add a row to `coord/CONTRACT.md` in a PR that touches nothing else: `status/gemini` (producer hub, consumer console), shape `{"mode":"off|replay|live","calls_last_hour":0,"stand_ins":["vision","tts"]}`, published every 2 s by the hub. The console badge (added in T20): `GEMINI: LIVE` green, `REPLAY` amber, `OFF` grey, with the stand-in list in a tooltip. Live and Gemma sessions (T21, T22, T15) use their own client but still call `gem.mark_stand_in` and count toward the cap.

**Test:** `coord/tests/test_gem.py`: `off` raises `GeminiOff` and never imports `google.genai`; `replay` returns a cached file without a network call (write the cache file in the test); the cap raises when exceeded (patch `CAP=2`); a 503 retries (monkeypatch `_c`).

**Done when:** `GEMINI_MODE=off pytest -q` is green across the repo with no key set, and the board has a post telling every lane to call Gemini only through `gem.ask` and to label any stand-in.

---

## T27 | shared | Antigravity: at most two named jobs (optional)
Depends on: T05, T26. Owner: lead. Only if time allows on Sunday morning. Antigravity is the heavy, sandboxed path; we spend it where a hosted sandbox earns its cost.

**What:** job A1 is an independent test suite for the physics route check, written and run by Antigravity as evidence of a real verification step (the guide lists "an Antigravity test suite" as one). Job A2 is the photo-scene critique, only if the local loop in T07 cannot reach a loadable scene. Nothing else uses Antigravity.

**How:** A1, one call (the code is pasted into the prompt, so no repo clone and no GitHub token are needed):
```python
from google import genai
client = genai.Client()
src = open("sim/physics.py").read()
interaction = client.interactions.create(
    agent="antigravity-preview-09-2026",
    agent_config={"type": "antigravity", "model": "gemini-4-argon"},
    input=("Here is a MuJoCo route verifier. Without changing it, write an independent pytest suite for verify_route: "
           "a leaning block that falls, a stable block that does not, determinism across 3 runs. "
           "pip install mujoco numpy pytest, run the suite, report failures and any bug you find.\n\n" + src),
    environment="remote")
open("docs/antigravity_report.md", "w").write(interaction.output_text)
```
Read the report and have the sim owner fix anything real with Claude or Codex, not with Antigravity. Quote the result in the one-page summary as independent verification. If the sandbox cannot install MuJoCo, say so in the report and drop A1; do not retry in a loop.

**Done when:** `docs/antigravity_report.md` exists with the sandbox's own test results, or the task is closed on the board as "skipped, local tests are enough" with the reason.
