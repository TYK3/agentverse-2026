"""LEVELS-LIVE selects real ramp physics through sim.start; no Responder is invented."""

import asyncio
import inspect
import json
from collections import defaultdict

import pytest

import sim
from sim import scene, sensors
from sim.levels import LevelWorld, max_jump


class Bus:
    def __init__(self):
        self.sent, self.subs = [], defaultdict(list)

    def subscribe(self, topic, callback):
        self.subs[topic].append(callback)

    async def publish(self, topic, data):
        self.sent.append((topic, data))
        for callback in tuple(self.subs[topic]):
            result = callback(data)
            if inspect.isawaitable(result):
                await result


@pytest.fixture
def levels_env(monkeypatch):
    monkeypatch.setenv("SIM_SCENE", "levels")
    monkeypatch.delenv("AFTERSHOCK_HW", raising=False)
    monkeypatch.delenv("SIM_RECORD", raising=False)
    # These tests exercise physics and transport, not OpenGL; no native contexts to leak.
    monkeypatch.setattr(sensors, "make_renderer", lambda *args, **kwargs: None)


def test_levels_is_a_named_scene():
    assert scene.resolve("levels") == ("levels", scene.SCENES / "levels.xml")


def test_shared_start_drives_scripted_bus_commands_to_b1_and_records_truth(levels_env, monkeypatch, tmp_path):
    output = tmp_path / "levels.jsonl"
    monkeypatch.setenv("SIM_RECORD", str(output))

    async def run():
        bus = Bus()
        world = await sim.start(bus, loop=False)
        assert isinstance(world, LevelWorld) and world.scene == "levels"
        assert world.responder is None
        try:
            assert next(data for topic, data in bus.sent if topic == "scene/loaded")["scene"] == "levels"
            # Scripted transport/physics proof only; the autonomous planner is not used here.
            for target in ([1.2, 2.1, 0.6], [3.8, 2.1, 0.0], [3.8, 0.3, 0.0], [1.3, 0.3, -0.6]):
                await bus.publish("scout/goto", {"target": target, "reason": "scripted hub-path regression"})
                for _ in range(600):
                    world.tick(0.1)
                    if world.state != "moving":
                        break
                assert world.state == "arrived", (target, world.pos.tolist())
            assert world.level() == "B1" and max_jump(world.trace) < 0.035
            await bus.publish("sensors/scout", world.sensors_message(camera=False))
            await bus.publish("route/proposed", {"id": "no-responder", "robot": "responder",
                              "cells": [[26, 6, -12]], "goal": "transport test", "model": "gemma-4-local"})
            verification = next(data for topic, data in bus.sent if topic == "route/verified")
            assert verification["ok"] is False and "no Responder" in verification["detail"]
        finally:
            world.recorder.close()
    asyncio.run(run())
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert rows[0]["data"]["scene"] == "levels"
    truth = [row["data"] for row in rows if row["topic"] == "sim/truth"]
    assert truth and truth[-1]["scout"]["pos"][2] == pytest.approx(-0.525)
    assert all("responder" not in data for data in truth)


def test_levels_source_runs_on_actual_hub_and_forwards_no_fictional_responder(levels_env, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("pydantic")
    from fastapi.testclient import TestClient

    from coord import hub

    target = hub.Bus()
    monkeypatch.setattr(hub, "bus", target)
    monkeypatch.setattr(hub, "LANES", ("sim",))
    original = hub.importlib.import_module

    def imports(name):
        if name == "coord.gem":
            raise ModuleNotFoundError(name=name)
        return original(name)

    monkeypatch.setattr(hub.importlib, "import_module", imports)
    routes = list(hub.app.router.routes)
    frames = []
    target.subscribe("sensors/scout", frames.append)
    try:
        with TestClient(hub.app) as client, client.websocket_connect("/ws") as browser:
            loaded = browser.receive_json()
            assert loaded["topic"] == "scene/loaded" and loaded["data"]["scene"] == "levels"

            async def sample():
                await asyncio.sleep(0.25)
            client.portal.call(sample)
            assert len(frames) >= 2 and frames[-1]["t"] > frames[0]["t"]
            assert frames[-1]["pose"]["pos"][2] == pytest.approx(0.675)
            assert not any(message["topic"] == "responder/pose" for message in target.history)
            assert client.post("/inject", json={"kind": "aftershock"}).status_code == 200
    finally:
        hub.app.router.routes[:] = routes
