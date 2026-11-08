# Real runs for replay

`real-run.jsonl` is the console's default replay (`/?run` in story mode). It is a real hub run, not demo
data: every lane on `coord.hub`, recorded by `SIM_RECORD` (sim/recorder.py) and slimmed with
`python -m sim.recorder slim` (10 Hz pose streams thinned, LiDAR and thermal arrays, status/gemini,
map/points and repeated map snapshots dropped; the first line says what was dropped). Every other
message is as the hub delivered it, in order, with sim time `t`.

This one: `python tools/demo.py --scene building --duration 120 --shift-at 70 --auto-approve`
(demo-20261108-025904.jsonl), GEMINI_MODE=off, 52.8 s of sim time, two triage gates auto-approved, the aftershock injected.
It is the building scene at ground level: the B1 rescue replaces it once the levels scene runs in the
hub (LEVELS-LIVE). To refresh: run tools/demo.py, then
`python -m sim.recorder slim console/public/runs/<run>.jsonl console/public/replays/real-run.jsonl`.
