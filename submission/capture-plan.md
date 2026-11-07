# Recording and rehearsal plan

The final video must be a continuous simulation take of no more than 60 seconds,
at 1920x1080. Put perception next to robot actions. Record the actual runtime with
the OS recorder or OBS; do not render an animation and describe it as a live run.

Before recording, confirm the organiser's deadline/timezone, merge-reviewed demo
revision, real lane status, edge-budget display and which model features are active.
Keep stand-in indicators visible. Do not claim a live model merely because its ID
appears in a log. Use a clean display without secrets or unrelated private windows.

| Time | Actual runtime evidence to capture |
| --- | --- |
| 0-10 s | Scene, Scout sensor feed and seen/inferred/unknown map; name the rescue goal. |
| 10-23 s | Casualty position/confidence, route proposal, physics result and confidence decision. |
| 23-30 s | Operator explicitly approves the requested risky action; Responder begins. |
| 30-40 s | Aftershock: old route is invalidated, Responder holds, Scout re-scans. |
| 40-52 s | A teammate injects a block at a location they choose during the take. Show its newly observed occupancy and the resulting changed route. |
| 52-60 s | Verified resumed action/delivery and handover; show unresolved risk if it cannot safely finish. |

This is a proposed shot schedule, not evidence that these timings are achievable.
If the real runtime takes longer, compress the scenario itself and rehearse; do
not cut or speed up the continuous take while claiming real-time adaptation.
Save a primary and spare take, the exact source SHA and the run JSONL beside each.

Rehearse the pitch twice aloud against a stopwatch. Record the actual durations
and tighten the text if it exceeds five minutes. Save a screen recording as backup.
Do not write "rehearsed" based on an estimated word count or generated speech.

Open the final PDF, video and README on a second machine. Record who checked and
the result. Once those checks pass, the lead chooses the final demo revision and
freeze time (at least two hours before the confirmed deadline), then authorises
the `demo-final` tag. This working pack creates no release tag.
