"""T10 checks: c1 found from thermal + sound on the T04 recording, thermal alone scores lower,
no casualty gives no entry, vision is gated and a flagged stand-in with Gemini off, frames are dropped."""

import itertools
import json
import math
import pathlib

import pytest

from perception.casualties import Casualties, column_bearing, thermal_region

RECORDING = pathlib.Path(__file__).resolve().parents[2] / "sim" / "recordings" / "scout_backup.jsonl"
C1 = (2.0, 1.0)       # casualty_c1 in sim/scenes/backup.xml


def frames():
    if not RECORDING.exists():
        pytest.skip("T04 recording sim/recordings/scout_backup.jsonl not present (#42)")
    return [json.loads(line)["data"] for line in RECORDING.read_text().splitlines() if line.strip()]


def run(c, data):
    for d in data:
        c.step(d)
    return c.message()


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_thermal_region_bearing():
    grid = [[0.1] * 16 for _ in range(12)]
    for r in range(5, 8):
        for col in (9, 10, 11):
            grid[r][col] = 0.7
    grid[6][10] = 0.9
    peak, col = thermal_region(grid)
    assert peak == 0.9 and col == pytest.approx(10.0)
    assert math.degrees(column_bearing(col)) == pytest.approx(-9.375)   # right of centre is negative
    edge = [[0.1] * 16 for _ in range(12)]
    edge[6][0] = 0.9
    assert thermal_region(edge) is None                                 # clipped at the edge: no bearing


def test_c1_found_from_two_clues():
    out = run(Casualties(vision_on=lambda: False), frames())
    assert len(out) == 1, out
    c1 = out[0]
    assert c1["id"] == "c1" and c1["confidence"] >= 0.7
    assert {"thermal", "sound"} <= set(c1["clues"])
    assert math.dist(c1["pos"][:2], C1) < 0.25, c1["pos"]
    assert c1["vitals"]["simulated"] is True
    assert set(c1) == {"id", "pos", "confidence", "clues", "vitals"}


def test_thermal_only_scores_lower():
    quiet = [{**d, "acoustic": {"bearing": 0.0, "level": 0.0}} for d in frames()]
    out = run(Casualties(vision_on=lambda: False), quiet)
    assert len(out) == 1 and out[0]["clues"] == ["thermal"]
    assert out[0]["confidence"] < 0.7


def test_no_casualty_no_entry():
    empty = [{**d, "thermal": [[0.1] * 16 for _ in range(12)], "acoustic": {"bearing": 30.0, "level": 0.02}}
             for d in frames()]
    assert run(Casualties(vision_on=lambda: False), empty) == []


def test_sound_alone_gives_no_entry():
    deaf = [{**d, "thermal": [[0.1] * 16 for _ in range(12)]} for d in frames()]
    assert run(Casualties(vision_on=lambda: False), deaf) == []


def test_vision_is_gated_and_frames_dropped():
    calls = []

    def ask(prompt, b64):
        calls.append(b64)
        assert "Do not describe faces" in prompt
        return '{"person": true, "bbox": [1, 2, 3, 4], "posture": "lying"}'

    clock = Clock()
    c = Casualties(ask=ask, clock=clock)
    data = frames()
    for d in data:
        clock.t = d["t"]
        c.step({**d, "camera": {"format": "jpeg", "b64": f"FRAME{d['t']}"}})
    assert calls, "vision was never asked"
    times = [float(b[5:]) for b in calls]
    assert all(b - a >= 1.0 - 1e-9 for a, b in itertools.pairwise(times))  # at most once a second
    first_clue = next(d["t"] for d in data if max(map(max, d["thermal"])) > 0.6 or d["acoustic"]["level"] > 0.1)
    assert times[0] >= first_clue                                           # only once a clue suggests someone
    c1 = c.message()[0]
    assert "pose" in c1["clues"] and c1["confidence"] >= 0.9
    assert "FRAME" not in json.dumps({k: v for k, v in vars(c).items() if k not in ("ask", "vision_on", "clock")},
                                     default=str)                           # no frame kept anywhere


def test_gemini_off_marks_vision_stand_in():
    asked = []
    c = Casualties(ask=lambda p, b: asked.append(b), vision_on=lambda: False)
    for d in frames()[:120]:
        c.step({**d, "camera": "FRAME"})
    assert asked == [] and c.vision_stand_in
    assert all("pose" not in e["clues"] for e in c.message())
