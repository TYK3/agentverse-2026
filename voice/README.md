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

```bash
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

## Spoken guidance, translation, cited first aid (T22)

- **Spoken Guidance (TTS) (`voice/speak.py`)**: Subscribes to `say` messages. Synthesises speech using `gemini-3.8-flash-tts` and plays audio with `sounddevice`. When `GEMINI_MODE=off` or if audio/hardware fails, it falls back safely to text-only output and records the stand-in.
- **Casualty Translation (`voice/translate.py`)**: For `say` messages with `to: "casualty"`, translates into the chosen casualty language (**Turkish / `tr`**, selected for earthquake search-and-rescue scenarios), and translates casualty responses back to English for the operator. In `GEMINI_MODE=off`, returns `[translation unavailable: gemini off]` and marks the stand-in.
- **Cited First Aid Guidance (`voice/firstaid.json`, `voice/firstaid.py`)**: Holds 6 short first aid steps (checking breathing, controlling bleeding, protecting spine/neck, recovery position, keeping warm/preventing shock, reassuring casualty). Every step carries an authoritative source URL (British Red Cross, NHS UK, St John Ambulance) and is strictly delivered as human guidance, never a medical diagnosis.
- **Emergency Call Preparation (`voice/emergency.py`)**: Formats structured emergency call reports with location cell, detection clues, and simulated vitals (explicitly marked simulated). Generates and publishes `gate/request` with `kind: "emergency_call"`. Voice never calls anyone directly without operator gate approval.
- **Hub Integration (`voice/__init__.py`)**: Exposes `async def start(bus)` called by the hub on startup, subscribing to the `say` topic.

## Running Checks

```bash
# Run CI check script:
bash voice/check.sh

# Run pytest suite:
pytest voice/tests -v

# Run ruff linter:
ruff check voice
```
