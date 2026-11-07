# voice lane: talking to the operator and the casualty

Spec: Function 6 of `docs/aftershock.md`.

Owns: operator voice commands with `gemini-3.8-live`, including a change of mind mid-sentence ("send
water to the left room, no, the back room"), resolved into one `operator/command`; spoken answers with
`gemini-3.8-flash-tts`; translation with `gemini-3.5-live-translate-preview` so a trapped person speaks
their own language; short, cited first aid steps read out as guidance only (no diagnosis, anything
medical needs a human to approve); and preparing the emergency call report, which only goes out after
a human confirms through the gate.

Ships first: a text-only stand-in that prints `say` messages and turns typed text into
`operator/command`, so the planner and console can work before audio does.

Owner: see the owner table in `AGENTS.md`. Only this lane's agent edits files here; others ask on the board.
