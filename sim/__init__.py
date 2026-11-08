"""sim lane: the MuJoCo world. The hub (coord/hub.py) calls `start(bus)` on startup."""

import asyncio
import logging
import os
import time

from sim import debris, inject, responder, rgbd, scene
from sim.world import World

RATE_HZ = 10
RGBD_EVERY = 5   # ticks between depth frames: 2 Hz of sensors/scout.points (Y9)
CLOCKS = ("wall", "step")
log = logging.getLogger("sim")


def clock():
    """SIM_CLOCK=wall (default): pace ticks to real time. step: fixed dt, no wall-clock wait."""
    name = os.environ.get("SIM_CLOCK", "wall").strip().lower() or "wall"
    if name not in CLOCKS:
        raise ValueError(f"SIM_CLOCK={name!r}: expected one of {', '.join(CLOCKS)}")
    return name


async def run(world, bus, rate_hz=RATE_HZ):
    """Tick the world; publish its events and sensors/scout at rate_hz of sim time.

    With SIM_CLOCK=step each tick advances exactly dt and only yields to the other lanes, so a run
    no longer depends on how busy the machine is; the default keeps the real-time pace.
    """
    dt = 1.0 / rate_hz
    step = clock() == "step"
    while True:
        started = time.monotonic()
        if world.responder is not None:
            world.responder.step(dt)  # the Responder (T06) moves on the same tick as the physics
        events = world.tick(dt)
        if world.responder is not None:
            events.append(("responder/pose", world.responder.pose_message(world.t)))  # E2: real pose, 10 Hz
        if getattr(world, "relay", None) is not None:  # L3: move the radio, drop crumbs, re-route
            events += world.relay.step(world.t, world.pos)
            world.hw.source.transport.flush()
        sensors = world.sensors_message()
        if getattr(world, "rgbd", None) is not None and round(world.t / dt) % RGBD_EVERY == 0:
            sensors.update(world.rgbd.frame(world.d) or {})   # Y9: measured depth points + camera position
        hw_robot = getattr(world, "hw", None)
        if hw_robot is not None:  # Y10: through the chip driver stubs and the bridge
            hw_robot.feed(sensors)
        else:
            events.append(("sensors/scout", sensors))
        for topic, data in events:
            try:
                await bus.publish(topic, data)
            except Exception:  # a rejected message must not stop the world
                log.exception("publish %s failed", topic)
        await asyncio.sleep(0.0 if step else max(0.0, dt - (time.monotonic() - started)))


def _walls(world):
    """Walls and rubble between two points at antenna height, for the relay's link budget (L3)."""
    from sim import sensors

    def walls(a, b):
        p, q = (a[0], a[1], 0.15), (b[0], b[1], 0.15)
        return 0 if p[:2] == q[:2] else sensors.walls_between(world.m, world.d, p, q, -1, -1)

    return walls


async def start(bus, loop=True):
    """Load the scene (SIM_SCENE, default backup) and wire the sim lane to the bus.

    Publishes scene/loaded; follows scout/goto; answers route/proposed with route/verified from a
    cached physics check; streams sensors/scout at 10 Hz and world/change after an aftershock or an
    injected block. On the hub it also serves POST /inject (sim/inject.py). The Responder (T06,
    sim/responder.py, `world.responder`) follows route/proposed, gate/* and responder/action, freezes
    on world/change and reports every outcome as log/decision.
    """
    name, path = scene.resolve()          # SIM_SCENE=backup (default) | tower | building | levels | MJCF path
    if name == "levels":
        from sim.levels import LevelWorld

        world = LevelWorld(path=path)
    else:
        world = World(path=path)
    world.scene = name
    from sim import recorder  # here, so `python -m sim.recorder` imports it only once

    world.recorder = recorder.attach(world, bus)   # S1: SIM_RECORD=file.jsonl records the run
    await bus.publish("scene/loaded", scene.scene_loaded(world.m, world.d, scene=name))
    bus.subscribe("scout/goto", world.goto)
    bus.subscribe("say", world.on_say)  # L2: the casualty knocks back when the Scout calls out
    # The Responder subscribes to route/proposed first: the hub runs callbacks in order and the
    # physics check below publishes route/verified, which can trigger the planner's whole
    # move/place/release dispatch before later callbacks run (seen in a real-lane run).
    # The levels scene contains only a Scout; never invent a Responder or approve its motion.
    world.responder = None if name == "levels" else responder.attach(world, bus)
    try:
        # Y9: the Scout's depth camera; a true-scale robot scene names its own (world.camera_name, #122)
        world.rgbd = rgbd.RGBD(world.m, camera=getattr(world, "camera_name", rgbd.CAMERA))
    except KeyError:                    # a scene without scout_cam: no depth points
        world.rgbd = None

    async def on_route(route):
        verification = world.verify(route) if world.responder is not None else {
            "id": route["id"], "ok": False, "unstable_cells": [],
            "detail": "levels scene has no Responder; movement verification unavailable",
        }
        await bus.publish("route/verified", verification)

    bus.subscribe("route/proposed", on_route)
    inject.install(world, bus)
    world.relay = None
    if os.environ.get("AFTERSHOCK_HW") == "1":
        import hw

        transport = None
        if os.environ.get("AFTERSHOCK_RELAY") == "1":  # L3: the Scout's data hops back over relays
            from hw import bridge, relay

            world.relay = relay.Relay(base=world.pos, walls=_walls(world))
            transport = relay.RelayTransport(bridge.from_env(), world.relay)
        world.hw = hw.attach(bus, transport=transport)
    if loop:
        debris.attach(world, bus)  # Y8: world/debris (sim truth, for scoring and the console)
        world.task = asyncio.create_task(run(world, bus))
    return world
