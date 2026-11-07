# voice lane: talking to people

Owns: speech recognition and speech generation on the rover, the triage dialogue ("Can you hear me?
Are you hurt? Can you move? Is anyone else with you?"), the knock-twice fallback, the priority each
conversation produces, and the judge-as-victim microphone path for the demo.

Ships first: a text-in, text-out dialogue that returns a triage result, so autonomy can use it
before audio works.

Owner: see the owner table in `AGENTS.md`. Only this lane's agent edits files here; others ask on the board.
