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
