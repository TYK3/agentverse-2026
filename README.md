# AFTERSHOCK

A light Scout maps a collapsed building. A heavier Responder delivers help along
routes checked by physics, with an operator approving risky work. When an
aftershock or a newly observed obstacle changes the scene, the system invalidates
the old route, re-scans and re-plans.

Built for the AgentVerse 2026 robotics track, 7-8 November 2026. This is a simulation
prototype, not a certified rescue, medical or structural engineering system.

## Run the development system

Python 3.12, MuJoCo and a browser are required. From the repo root:

```sh
python -m venv .venv
# Activate .venv using the command for your shell.
python -m pip install -r requirements.txt -r coord/requirements.txt
python tools/mujoco_check.py
uvicorn coord.hub:app --port 8000
```

In another terminal:

```sh
cd console
npm ci
npm run dev -- --port 5173
```

Open `http://localhost:5173`; `http://localhost:8000/docs` exposes the gateway docs.
The five lane PRs are being integrated. A running console is not evidence that a
full mission or every model feature works. `GEMINI_MODE=off` is the default; keep
stand-in labels visible. Never commit an API key or local environment file.

## Perceive, decide, act

Simulated LiDAR, camera, thermal and acoustic sensors feed perception. Map cells
are seen, inferred or unknown; inferred cells do not count as confirmed safe.
The local planner proposes a route, MuJoCo checks instability, the confidence
gate acts/re-looks/refers, and a person explicitly approves risky actions.
Only then does the Responder act. Scene changes cancel the old plan and require
fresh evidence. The handover records observations, routes, changes and approvals.

Lanes expose `async start(bus)` and use `Bus.subscribe(topic, callback)` and
`await Bus.publish(topic, data)`. The console receives `{topic,data}` events via
`/ws`. See [the interface contract](coord/CONTRACT.md), [project context](coord/CONTEXT.md)
and [the functional spec](docs/aftershock.md).

## Models and runtime placement

| Job | Exact identifier | Placement / evidence |
| --- | --- | --- |
| Core routes | `local-astar` | Local Python CPU; cloud independent, physics/gate still required |
| Scene interpretation and optional route review | `gemini-4-argon` | Cloud, through `coord/gem.py`; full live integration pending |
| Handover drafting | `gemini-3.8-flash` | Optional cloud refinement; structured log remains the source of truth |
| Operator speech | `gemini-3.8-live` | Cloud; typed twin available |
| Spoken guidance | `gemini-3.8-flash-tts` | Cloud; labelled text stand-in when inactive |
| Casualty translation | `gemini-3.5-live-translate-preview` | Cloud; live validation pending |
| Offline goal reading | `gemma4:e2b` (Q4_K_M), Ollama 0.40.15 | Local CPU target; routing and safety remain local rules |

PR #55's budget configuration reports an 8 GB CPU/WSL2 target, about 4.1 GB model
resident memory, warm goal reads of 1.8-2.8 s and a 19 s cold load. Its demo uses
a scripted physics verdict. These are offline-lane measurements, not an
independently replicated full-system latency. The budget meter has 5000 MB and
4000 ms per-step limits; final hardware and latency evidence still needs capture.

## Evidence and limits

The hub's initial PR #47 passed 42 transport/schema tests plus five sim checks,
live HTTP and a typed WebSocket round trip. The evolving integration has its own
tests; use the current lane check scripts and PR evidence for current results.

The #32 draft harness compares paired seeded scenarios and measures safe success,
not raw arrival. Its development grid-world run measured naive 25/30 versus T12
router 30/30 safe successes. It includes oracle perception, scripted collapse,
grid dynamics, a test operator and no MuJoCo verification. These figures are
**not full-system results**; the real Responder-trace adapter is still being built.

Casualty positions and confidence replace facial identification. Vitals are
simulated; hazard estimates are labelled. Medical guidance and emergency calls
require a human. A second collapse is the critical failure mode; stopping for a
re-scan or referring to an operator is an expected result when evidence is weak.

## Submission and collaboration

[Submission review pack](submission/README.md): one-page PDF source, pitch text,
capture plan and evidence status. The final continuous demo video, two timed pitch
rehearsals, organiser deadline, different-machine checks and demo freeze/tag are
pending. The [track brief](docs/brief.md) states the required deliverables.

The team coordinates on [board issue #1](https://github.com/TYK3/agentverse-2026/issues/1).
Read [AGENTS.md](AGENTS.md) and [PLAYBOOK.md](PLAYBOOK.md) before contributing.
Run `bash tools/setup` once, set your agent identity, read `bash tools/board unread`,
and use PRs for changes. Do not merge or push to main without the lead's instruction.
