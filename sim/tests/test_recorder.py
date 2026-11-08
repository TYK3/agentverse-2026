"""S1 checks: SIM_RECORD writes every bus message plus 3D sim truth as replayable JSONL."""

import asyncio
import inspect
import itertools
import json

import pytest

import sim
from sim import recorder


class Bus:
    """The hub Bus's delivery rules without its validation: subscribers in order, sync or async."""

    def __init__(self):
        self.subs = {}

    def subscribe(self, topic, fn):
        self.subs.setdefault(topic, []).append(fn)

    async def publish(self, topic, data):
        for fn in tuple(self.subs.get(topic, ())):
            out = fn(data)
            if inspect.isawaitable(out):
                await out


def _run(bus, seconds, extra=None):
    async def main():
        world = await sim.start(bus)
        if extra:
            await extra(bus)
        await asyncio.sleep(seconds)
        world.task.cancel()
        world.recorder.close()
        return world

    return asyncio.run(main())


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_records_bus_messages_and_3d_truth(tmp_path, monkeypatch):
    out = tmp_path / "run.jsonl"
    monkeypatch.setenv("SIM_RECORD", str(out))

    async def planner_and_console(bus):
        await bus.publish("permit/route", {"route": "r1", "granted": False})
        await bus.publish("gemini/receipt", {"id": "gem-1", "route": "r1"})
        await bus.publish("map/casualties", [{"id": "c1", "pos": [2.0, 1.0, 0.0], "confidence": 0.7}])

    world = _run(Bus(), 1.5, planner_and_console)
    lines = _lines(out)
    topics = [x["topic"] for x in lines]
    assert topics[0] == "record/meta" and topics[1] == "scene/loaded"        # recorded from the start
    assert {"permit/route", "gemini/receipt", "map/casualties", "sensors/scout", "sim/truth"} <= set(topics)
    assert all(set(x) == {"t", "wall", "topic", "data"} for x in lines)
    truth = [x for x in lines if x["topic"] == "sim/truth"]
    assert 10 <= len(truth) <= 20                                            # one per tick: 10 Hz
    assert [round(b["t"] - a["t"], 2) for a, b in itertools.pairwise(truth)] == [0.1] * (len(truth) - 1)
    last = truth[-1]["data"]
    assert len(last["scout"]["pos"]) == 3 and len(last["responder"]["pos"]) == 3
    assert set(last["casualties"]) == {"c1"} and len(last["casualties"]["c1"]) == 3
    sensors = [x["data"] for x in lines if x["topic"] == "sensors/scout"]
    assert sensors and all("camera" not in s for s in sensors) and len(sensors[0]["lidar"]) == 360
    assert out.read_text(encoding="utf-8").endswith("\n") and world.recorder.file.closed


def test_summary(tmp_path, monkeypatch):
    out = tmp_path / "run.jsonl"
    monkeypatch.setenv("SIM_RECORD", str(out))
    _run(Bus(), 1.0)
    s = recorder.summary(out)
    assert s["topics"]["record/meta"] == 1 and s["topics"]["scene/loaded"] == 1
    assert 9 <= s["truth_hz"] <= 11


def test_off_without_sim_record(tmp_path, monkeypatch):
    monkeypatch.delenv("SIM_RECORD", raising=False)
    monkeypatch.chdir(tmp_path)
    world = asyncio.run(sim.start(Bus(), loop=False))
    assert world.recorder is None and not list(tmp_path.iterdir())


def test_with_the_real_hub_bus(tmp_path, monkeypatch):
    hub = pytest.importorskip("coord.hub")
    out = tmp_path / "hub.jsonl"
    monkeypatch.setenv("SIM_RECORD", str(out))
    _run(hub.Bus(), 1.0)
    topics = {x["topic"] for x in _lines(out)}
    assert {"record/meta", "scene/loaded", "sensors/scout", "sim/truth"} <= topics


def test_slim_keeps_the_story_and_drops_the_bulk(tmp_path):
    src, dst = tmp_path / "full.jsonl", tmp_path / "slim.jsonl"
    lines = [{"t": 0, "wall": 0.0, "topic": "record/meta", "data": {"scene": "building"}},
             {"t": 0, "wall": 0.0, "topic": "scene/loaded", "data": {"scene": "building", "blocks": []}}]
    for i in range(10):
        t = round(0.1 * (i + 1), 1)
        lines += [{"t": t, "wall": t, "topic": "sensors/scout",
                   "data": {"t": t, "pose": {"pos": [0, 0, 0.26], "yaw": 0}, "lidar": [6.0] * 360,
                            "thermal": [[0.1] * 16] * 12, "acoustic": {"bearing": 0, "level": 0.1}}},
                  {"t": t, "wall": t, "topic": "sim/truth", "data": {"scout": {"pos": [0, 0, 0]}}},
                  {"t": t, "wall": t, "topic": "status/gemini", "data": {"mode": "off"}}]
    snap = {"t": 1.0, "res": 0.05, "cells": [{"cell": [1, 2, 0], "state": "seen", "occupied": True}]}
    lines += [{"t": 1.0, "topic": "map/cells", "data": snap}, {"t": 1.05, "topic": "map/cells", "data": {**snap, "t": 1.05}},
              {"t": 1.1, "topic": "map/cells", "data": {"t": 1.1, "res": 0.05, "cells": []}},
              {"t": 1.15, "topic": "map/cells", "data": snap}]
    lines += [{"t": 1.2, "wall": 1.3, "topic": "world/change", "data": {"kind": "aftershock", "t": 1.2, "moved_blocks": []}}]
    src.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")
    n_in, n_out = recorder.slim(src, dst)
    out = _lines(dst)
    assert n_in == len(lines) + 1 and n_out == len(out)
    topics = [x["topic"] for x in out]
    assert topics[:2] == ["record/meta", "scene/loaded"] and topics[-1] == "world/change"
    assert "status/gemini" not in topics
    assert topics.count("sensors/scout") == 5 and topics.count("sim/truth") == 2
    assert [len(x["data"]["cells"]) for x in out if x["topic"] == "map/cells"] == [1, 0, 1]   # repeat dropped
    scout = next(x["data"] for x in out if x["topic"] == "sensors/scout")
    assert set(scout) == {"t", "pose", "acoustic"} and scout["pose"]["pos"][2] == 0.26      # z kept
    assert out[0]["data"]["slimmed"]["dropped_topics"] == ["status/gemini", "map/points"]
    assert all("wall" not in x for x in out)
    ts = [x["t"] for x in out]
    assert ts == sorted(ts)
