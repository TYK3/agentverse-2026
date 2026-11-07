"""Measured MuJoCo trials using production lane classes on a simulation clock.

Requires T05/T06/T09/T10/T11/T13. No fake map, casualty confidence, physics verdict
or robot trajectory is substituted. A trial that times out without reaching the
goal is a measured non-success. Disabled cloud vision/review are named explicitly.
"""

import asyncio
import hashlib
import heapq
import json
import math
import os
import random
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

SIM_SECONDS = 120.0
DT = 0.1
AFTERSHOCK_AT = 25.0
RES = 0.05


def seeded_xml(source, seed):
    """Small bounded rubble perturbations, same building; casualty varies within room 3."""
    rng = random.Random(seed)
    root = ET.fromstring(source)
    bodies = {body.get("name"): body for body in root.iter("body")}
    for name in ("b11", "b12", "b13", "b14", "b15"):
        body = bodies[name]
        pos = [float(v) for v in body.get("pos").split()]
        pos[0] += rng.uniform(-0.04, 0.04)
        pos[1] += rng.uniform(-0.04, 0.04)
        body.set("pos", " ".join(f"{v:.6f}" for v in pos))
    casualty = bodies["casualty_c1"]
    casualty.set("pos", f"{rng.uniform(1.85, 2.15):.6f} {rng.uniform(0.95, 1.2):.6f} 0.12")
    data = ET.tostring(root, encoding="utf-8")
    config = {"xml_sha256": hashlib.sha256(data).hexdigest(), "aftershock_at": AFTERSHOCK_AT,
              "sim_seconds": SIM_SECONDS, "dt": DT, "res": RES}
    fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    return data, fingerprint


def cell_at(pos):
    return [math.floor(float(pos[0]) / RES), math.floor(float(pos[1]) / RES), 0]


def shortest_known_free(records, start, goal):
    """Eight-connected Dijkstra; no hazard/clearance costs or physics verification."""
    free = {key for key, value in records.items()
            if value["state"] != "unknown" and not value["occupied"]}
    start, goal = tuple(start), tuple(goal)
    if start not in free or goal not in free:
        return None
    queue, cost, came = [(0.0, start)], {start: 0.0}, {start: None}
    while queue:
        distance, current = heapq.heappop(queue)
        if distance != cost[current]:
            continue
        if current == goal:
            path = []
            while current is not None:
                path.append(list(current))
                current = came[current]
            return path[::-1]
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not (dx or dy):
                    continue
                nxt = (current[0] + dx, current[1] + dy, 0)
                if nxt not in free:
                    continue
                if dx and dy and ((current[0] + dx, current[1], 0) not in free
                                  or (current[0], current[1] + dy, 0) not in free):
                    continue
                value = distance + math.hypot(dx, dy)
                if value < cost.get(nxt, math.inf):
                    came[nxt], cost[nxt] = current, value
                    heapq.heappush(queue, (value, nxt))
    return None


async def run_trial(*, seed, planner):
    if os.environ.get("GEMINI_MODE", "off") != "off":
        raise ValueError("T24 local evaluation requires GEMINI_MODE=off")
    # Import only when running; capability failures must not silently select fakes.
    from perception.casualties import Casualties
    from perception.hazards import Hazards
    from sim.responder import REACH, Responder

    from coord.messages import validate_payload
    from perception.explore import Explorer
    from perception.grid import Grid
    from planner.loop import Loop
    from planner.route import RoutePlanner
    from sim import aftershock, scene
    from sim.world import World

    events, bus_messages, message_counts = [], [], {}
    pending_logs = []

    class Bus:
        # Fail visibly on handler errors, rather than recording a successful trial.
        def __init__(self):
            self.subs = {}

        def subscribe(self, topic, callback):
            self.subs.setdefault(topic, []).append(callback)

        async def publish(self, topic, data):
            import inspect
            data = validate_payload(topic, data)
            message_counts[topic] = message_counts.get(topic, 0) + 1
            if topic not in ("sensors/scout", "map/cells"):
                bus_messages.append({"t": world.t, "topic": topic, "data": data})
            if topic == "route/proposed":
                events.append({"t": world.t, "kind": "route", "id": data["id"]})
            if topic == "gate/answer":
                events.append({"t": world.t, "kind": "approval", "id": data["id"],
                               "approved": data["approved"]})
            for callback in tuple(self.subs.get(topic, [])):
                result = callback(data)
                if inspect.isawaitable(result):
                    await result

    source = Path(scene.BACKUP).read_bytes()
    xml, fingerprint = seeded_xml(source, seed)
    with tempfile.TemporaryDirectory(prefix="aftershock-eval-") as directory:
        path = Path(directory) / "seeded.xml"
        path.write_bytes(xml)
        world = World(path=path, seed=seed, render=False)
        bus = Bus()
        responder = Responder(world.m, world.d,
                              publish=lambda topic, data: pending_logs.append((topic, data)),
                              clock=lambda: world.t)
        bus.subscribe("route/proposed", responder.on_route)
        bus.subscribe("responder/action", responder.on_action)
        bus.subscribe("gate/request", responder.on_gate_request)
        bus.subscribe("gate/answer", responder.on_gate_answer)
        if planner == "aftershock":
            bus.subscribe("world/change", responder.on_world_change)
        router = RoutePlanner(bus)
        bus.subscribe("map/cells", router.update_map)
        bus.subscribe("map/hazards", router.update_hazards)
        controller = Loop(bus, router, clock=lambda: world.t).attach() if planner == "aftershock" else None

        async def verify(data):
            if controller is not None:
                await bus.publish("route/verified", world.verify(data))

        async def approve(data):
            await bus.publish("gate/answer", {"id": data["id"], "approved": True, "by": "operator"})

        bus.subscribe("route/proposed", verify)
        bus.subscribe("gate/request", approve)
        grid, hazards = Grid(), Hazards()
        explorer = Explorer(grid)
        casualty = Casualties(clock=lambda: world.t, vision_on=lambda: False)
        bus.subscribe("scout/goto", world.goto)
        bus.subscribe("scout/goto", lambda data: explorer.on_goto(data, world.t))
        bus.subscribe("gate/decision", lambda data: explorer.on_decision(data, world.t))
        bus.subscribe("map/hazards", explorer.on_hazards)
        bus.subscribe("world/change", explorer.on_change)

        async def changed(data):
            await bus.publish("map/hazards", hazards.on_change(data))

        bus.subscribe("world/change", changed)
        description = scene.scene_loaded(world.m, world.d)
        explorer.on_scene(description)
        await bus.publish("scene/loaded", description)
        await bus.publish("map/hazards", hazards.on_scene(description))
        casualty_pos = [float(v) for v in world.d.geom_xpos[world.casualty_geom]]
        goal = cell_at(casualty_pos)
        start = cell_at(responder.pos)
        events.append({"t": 0, "kind": "position", "cell": start, "pos": [float(v) for v in responder.pos]})
        mission_started = False
        records, numbered = {}, 0
        shake_ids, shake_positions, initial_boxes = None, None, None
        collapsed, error = set(), ""
        for tick in range(round(SIM_SECONDS / DT)):
            # Same exogenous aftershock time for both planners, independent of their choices.
            if world.t >= AFTERSHOCK_AT and shake_ids is None:
                shake_ids = aftershock.candidate_blocks(world.m)
                shake_positions = world.d.xpos[shake_ids].copy()
                initial_boxes = {body: aftershock._box(world.m, world.d, body) for body in shake_ids}
                world.trigger_aftershock()
            messages = world.tick(DT)
            if shake_ids is not None:
                for body, initial in zip(shake_ids, shake_positions, strict=True):
                    if math.dist(world.d.xpos[body], initial) > aftershock.MOVED:
                        boxes = [initial_boxes[body], aftershock._box(world.m, world.d, body)]
                        area = {(*xy, 0) for box in boxes
                                for xy in aftershock.cells_near(box, margin=0, res=RES)}
                        new = area - collapsed
                        if new:
                            collapsed |= new
                            events.append({"t": world.t, "kind": "collapsed", "cells": sorted(new)})
            for topic, data in messages:
                await bus.publish(topic, data)
            sensors = world.sensors_message(camera=False)
            await bus.publish("sensors/scout", sensors)
            grid.add_sensors(sensors)
            explorer.on_sensors(sensors)
            casualty.dirty |= casualty.on_sensors(sensors)
            if tick % 5 == 0:
                msg = grid.snapshot(world.t) if tick % 50 == 0 else grid.delta(world.t)
                records.update({tuple(row["cell"]): row for row in msg["cells"]})
                # Re-plans must start at the measured Responder cell after a world change.
                if controller is not None and controller.mission_args:
                    controller.mission_args["start"] = tuple(cell_at(responder.pos))
                await bus.publish("map/cells", msg)
                detections = casualty.message()
                await bus.publish("map/casualties", detections)
                approaches = [key for key, record in records.items()
                              if record["state"] == "seen" and not record["occupied"]
                              and 0.33 <= math.dist([(key[0] + 0.5) * RES, (key[1] + 0.5) * RES],
                                                    casualty_pos[:2]) <= REACH - 0.02]
                if not mission_started and detections and approaches:
                    goal = list(min(approaches, key=lambda c: math.dist(
                        [(c[0] + 0.5) * RES, (c[1] + 0.5) * RES], responder.pos[:2])))
                    mission_started = True
                    if controller is not None:
                        await controller.mission(cell_at(responder.pos), goal)
                if planner == "naive" and mission_started and responder.state in ("idle", "blocked", "arrived"):
                    route = shortest_known_free(records, cell_at(responder.pos), goal)
                    if route:
                        numbered += 1
                        rid = f"naive-{numbered}"
                        await bus.publish("route/proposed", {"id": rid, "robot": "responder",
                            "cells": route, "goal": "reach seeded casualty", "model": "naive-shortest"})
                        await bus.publish("responder/action", {"action": "move", "route": rid, "item": "water"})
            if tick % 10 == 0:
                goto = explorer.tick(world.t)
                if goto:
                    await bus.publish("scout/goto", goto)
            responder.step(DT)
            for topic, data in pending_logs:
                await bus.publish(topic, data)
            pending_logs.clear()
            current = cell_at(responder.pos)
            events.append({"t": world.t, "kind": "position", "cell": current,
                           "pos": [float(v) for v in responder.pos]})
            if math.dist(responder.pos[:2], casualty_pos[:2]) <= REACH:
                break
            # Give cancellation/timeouts a chance even during CPU simulation.
            await asyncio.sleep(0)
        return {"seed": seed, "planner": planner, "goal": goal, "events": events,
                "completed": True, "backend": "MuJoCo + production perception/router/gate/Responder",
                "stand_ins": ["cloud-vision-off", "cloud-route-review-off", "test-operator"],
                "scenario_sha256": fingerprint, "bus_messages": bus_messages,
                "casualty_pos": casualty_pos, "reach_distance_m": REACH,
                "message_counts": message_counts,
                "source_revisions": json.loads((Path(__file__).resolve().parents[1] / "runtime_sources.json").read_text())
                if (Path(__file__).resolve().parents[1] / "runtime_sources.json").exists() else {},
                "sim_seconds": world.t, "final_responder_state": responder.state,
                "final_scout_state": world.state, "final_scout_pos": [float(v) for v in world.pos],
                "mission_started": mission_started,
                "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "error": error}
