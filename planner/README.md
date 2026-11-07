# planner lane: decisions

Spec: Functions 4, 5 and 7 of `docs/aftershock.md`.

Owns: route planning with `gemini-4-argon`; sending each route to the sim physics check and re-proposing
on failure; the confidence gate (act, re-look, refer to a human; never guess silently); visible
re-planning on a scene change; the Responder's tasks (deliver supplies, clear light debris, guide
escape); the human gate for risky moves and any 999 call; the reasoning log; offline planning with a
local Gemma 4 (E2B or E4B) re-checked by `gemini-4-argon` when back online; the edge budget; and the
handover report drafted by `gemini-3.8-flash`.

Ships first: a planner that runs on perception's fixtures and logs every decision with its perception,
model call, physics result and outcome.

Owner: see the owner table in `AGENTS.md`. Only this lane's agent edits files here; others ask on the board.
