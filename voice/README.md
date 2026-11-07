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

## Operator voice commands (T21)

```
python -m voice.typed                       # typed twin: one line in, one operator/command out
GEMINI_MODE=live python -m voice.operator   # hold SPACE, speak, release (needs voice/requirements.txt, a mic, GEMINI_API_KEY)
bash voice/check.sh                         # ruff + tests, GEMINI_MODE=off, no key or mic needed
```

- Publishes `operator/command {"text":"send water to the back room","source":"voice"|"typed"}` after any
  change of mind is resolved ("left room, no, the back room"). Texts: `send <water|the first aid kit|the
  radio> to the <place>`, `scan the <place>`, `stop`, `return to base`. Commands it cannot resolve are
  logged and not published.
- The live session (`gemini-3.8-live`) returns the final intent as JSON
  `{"goal":"deliver","item":"water","place":"back room"}`; push-to-talk turns off automatic voice
  detection so noise cannot trigger it. Without pynput or a display, Enter toggles talking.
- With `GEMINI_MODE=off` or no microphone, `voice.operator` falls back to the typed twin and says
  `[STAND-IN]` on stderr, in the transcript and (once `coord/gem.py` lands) in the Gemini badge.
- Every command, heard text, intent and result is logged to `voice/logs/transcript.jsonl` (gitignored;
  `VOICE_LOG` overrides the path).
- Until the hub (T02) merges, messages print to stdout as `operator/command {json}` (`command.StdoutBus`).
