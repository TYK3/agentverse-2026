# AFTERSHOCK submission pack

Review snapshot, 7 November 2026. The PDF and pitch distinguish verified work from
pending integration. This folder is not a claim that the final submission is ready.

- `output/pdf/aftershock-technical-summary.pdf`: one-page technical summary.
- `submission/pitch.md`: five-minute pitch text with demo cues.
- `submission/capture-plan.md`: one-take video and rehearsal plan.
- `submission/status.json`: evidence and unresolved submission facts.
- `submission/build_summary.py`: reproducible PDF source (`pip install reportlab pypdf`).

Build from the repository root:

```sh
python submission/build_summary.py
```

AFTERSHOCK helps search-and-rescue operators map a collapsed building with a light
Scout and route a heavier Responder toward casualties. The control loop is propose,
physics check, confidence gate, explicit operator approval when risky, then execute.
An aftershock cancels the previous route and requires a re-scan and re-plan.

Core route proposals use `local-astar` on the local CPU. Named cloud model IDs in
the project spec are `gemini-4-argon` (scene building and route review),
`gemini-3.8-flash` (handover), `gemini-3.8-live` (operator commands),
`gemini-3.8-flash-tts` (spoken guidance) and `gemini-3.5-live-translate-preview`
(casualty translation). Product calls must pass through `coord/gem.py`.
This pack does not claim all those models have been demonstrated end to end.
The offline goal reader is configured as `gemma4:e2b` (Q4_K_M), Ollama 0.40.15.
PR #55 reports an 8 GB CPU/WSL2 target, about 4.1 GB model memory, 1.8-2.8 s warm
goal reading and 19 s cold load, with a 5 GB / 4 s per-step budget. These are the
offline lane's reported measurements, not a replicated full-system measurement;
the offline demo uses a scripted physics verdict. Final runtime latency remains pending.

The only baseline numbers currently available are explicitly labelled grid-world
development results from #32: naive 25/30 safe successes and production T12 routing
30/30, with oracle perception, scripted collapse, grid dynamics, test operator and
no MuJoCo verification. They are not full-system or real-rescue results. Keep the
raw CSV/chart and their labels together. Replace them only with a measured real run.

Still required before final submission: organiser-confirmed Sunday time/timezone,
real integration evidence, budget-meter hardware/latencies, a <=60 s continuous
1080p demo recording with an unscripted change and a spare take, two timed pitch
rehearsals, different-machine open checks, and the lead's demo freeze/tag decision.
Do not tag `demo-final` while those are pending.
