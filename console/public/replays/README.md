# Committed replays

`b1-run.jsonl` is a real B1 rescue run, replayed by story mode at `/?run` (or `/?run=default`).
`/?run=<url>` still replays any other recording.

- Source: `GEMINI_MODE=off python tools/run_rescue.py --auto-approve --b1 --seed 16` (PR #52's runner)
  on main 9059bd7: every lane real on the hub Bus, nothing scripted.
- Result of this run: 15/16 runner steps. The one fail is "supply placed within 0.5 m of the
  casualty" (the known #52 fail); it will be swapped for the first 16/16 run.
- Slimmed for serving (9.5 MB to 2.9 MB), messages kept in order: `sensors/scout` dropped
  (raw sensors stay local), `responder/pose` and `_probe/pose` every 2nd message, a `map/cells`
  identical to the one before it dropped, `wall` removed. Same rules as #176's `sim.recorder slim`.
