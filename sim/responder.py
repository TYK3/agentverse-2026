"""The Responder (T06): a heavier robot that follows verified routes, carries supplies and clears light debris.

It is a mocap body in sim/scenes/backup.xml driven kinematically, cell to cell, at SPEED. Before every
step it casts collision rays ahead (two heights, centre line and both sides) and refuses to move into a
block, the same way the Scout does. Supplies and grippable blocks are held with MuJoCo weld equalities
(`carry_<item>`, `grip_<block>`): grip sets the held pose and switches the weld on, release switches it
off and the object falls.

Messages (coord/CONTRACT.md):
- in  `route/proposed`   remember the route's cells by id
- in  `gate/request`     a risky_move / enter_at_risk request marks its route as needing approval
- in  `gate/answer`      approved: true unlocks that route
- in  `responder/action` move | place_supply | grip | release; actions that arrive while a move is
                         running are queued and run in order when it ends (there is no completion message)
- in  `world/change`     freeze in place, drop the current move and the queue (wait for a new responder/action)
- in  `permit/route`     L1: granted false stops a move on that route at once and refuses new moves on it
                         until a granted true arrives (routes with no permit message behave as before)
- out `log/decision`     every action's outcome; refusals say outcome "refused" and why

Clearing debris is `grip_block(block_id)` / `release_block(block_id)`: responder/action's `item` only
names supplies, so the contract has no way to ask for a block yet (flagged on the board).
"""

import asyncio
import itertools
import math

import mujoco
import numpy as np

SPEED = 0.2                 # m/s
RES = 0.05                  # grid cell size, same as perception's map (cell = floor(pos / RES))
HALF_LEN, HALF_WIDTH = 0.16, 0.07   # chassis half extents (body x = forward)
GAP = 0.03                  # free space kept between the chassis front and anything ahead
RAY_HEIGHTS = (0.03, 0.09)  # world z of the collision rays (low rubble and wall height)
ARRIVE = 0.005              # metres
REACH = 0.45                # a supply or block further than this from the Responder centre cannot be gripped
LIGHT_KG = 2.0              # blocks at or above this mass are too heavy to clear
SUPPLIES = ("water", "first_aid_kit", "radio")
RISKY_KINDS = ("risky_move", "enter_at_risk")

# Held poses in the Responder frame: supplies sit in deck slots, a gripped block is lifted above them.
SLOTS = {"water": (-0.1, 0.0, 0.11), "first_aid_kit": (0.0, 0.0, 0.08), "radio": (0.1, 0.0, 0.095)}
BLOCK_SLOT_Z = 0.18         # above the tallest supply (water top is 0.17 over the Responder centre); add the block's half height
PLACE_AHEAD = 0.08          # place_supply sets the item down this far in front of the chassis


def cell_centre(cell, res=RES):
    """Scene-frame x, y of a grid cell's centre."""
    return np.array([(cell[0] + 0.5) * res, (cell[1] + 0.5) * res])


def cells_along(points, res=RES, k=0):
    """Grid cells visited walking straight between consecutive (x, y) points; a test and demo helper."""
    out = []
    for a, b in itertools.pairwise(points):
        a, b = np.asarray(a, float), np.asarray(b, float)
        n = max(1, math.ceil(np.linalg.norm(b - a) / (res / 2)))
        for s in range(n + 1):
            p = a + (b - a) * s / n
            c = [math.floor(p[0] / res), math.floor(p[1] / res), k]
            if not out or out[-1] != c:
                out.append(c)
    return out


class Responder:
    def __init__(self, m, d, publish=None, clock=None, shaking=None):
        """`publish(topic, data)` sends a message (default: drop it); `clock()` gives sim time in seconds;
        `shaking()` is true while a live aftershock runs (World.shaking): the Responder freezes at once."""
        self.m, self.d = m, d
        self.publish = publish or (lambda topic, data: None)
        self.clock = clock or (lambda: float(d.time))
        self.shaking = shaking or (lambda: False)
        self.body = m.body("responder").id
        self.mocap = int(m.body_mocapid[self.body])
        self.routes = {}           # route id -> list of cells
        self.risky = {}            # gate request id -> route id needing approval
        self.approved = set()      # route ids with an approved gate/answer
        self.needs_gate = set()    # route ids with an open risky gate request
        self.revoked = set()       # route ids whose move permit (L1, permit/route) is revoked
        self.path = []             # remaining (x, y) waypoints of the current move
        self.route = None
        self.state = "idle"        # idle | moving | arrived | blocked | frozen
        self.queue = []            # responder/action messages waiting for the current move to finish
        self.log = []              # every log/decision this Responder published

    # ---- pose -------------------------------------------------------------------
    @property
    def pos(self):
        return self.d.mocap_pos[self.mocap].copy()

    @property
    def yaw(self):
        w, _, _, z = self.d.mocap_quat[self.mocap]
        return 2.0 * math.atan2(z, w)

    def _set_pose(self, xy, yaw):
        self.d.mocap_pos[self.mocap][:2] = xy
        self.d.mocap_quat[self.mocap] = [math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2)]

    # ---- helpers ----------------------------------------------------------------
    def _eq(self, name):
        return mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_EQUALITY, name)

    def holding(self, name):
        """True while the weld for supply or block `name` is on."""
        eq = self._eq(("carry_" if name in SUPPLIES else "grip_") + name)
        return eq >= 0 and bool(self.d.eq_active[eq])

    def _hold(self, eq, rel):
        self.m.eq_data[eq, 3:6] = rel
        self.m.eq_data[eq, 6:10] = [1.0, 0.0, 0.0, 0.0]
        self.d.eq_active[eq] = 1

    def _distance(self, body_name):
        return float(np.linalg.norm(self.d.xpos[self.m.body(body_name).id][:2] - self.pos[:2]))

    def _decide(self, outcome, reason, action=""):
        x, y = (round(float(v), 2) for v in self.pos[:2])
        data = {
            "t": round(max(0.0, float(self.clock())), 2),
            "perception": f"responder at [{x}, {y}]" + (f", {action}" if action else ""),
            "model": "sim",
            "physics": "mujoco",
            "outcome": outcome,
            "reason": reason,
        }
        self.log.append(data)
        self.publish("log/decision", data)
        return data

    def _refuse(self, reason, action=""):
        return self._decide("refused", reason, action)

    # ---- message handlers -------------------------------------------------------
    def on_route(self, msg):
        if msg.get("robot", "responder") == "responder":
            self.routes[msg["id"]] = [list(c) for c in msg["cells"]]

    def on_gate_request(self, msg):
        if msg.get("kind") in RISKY_KINDS and msg.get("route"):
            self.risky[msg["id"]] = msg["route"]
            self.needs_gate.add(msg["route"])

    def on_gate_answer(self, msg):
        route = self.risky.get(msg.get("id"))
        if route and msg.get("approved") is True:
            self.approved.add(route)

    def on_world_change(self, msg):
        """An aftershock (or any world change) freezes the Responder and drops its move and queued actions."""
        if self.state == "moving" or self.queue:
            dropped = len(self.queue)
            self.path, self.queue, self.state = [], [], "frozen"
            self._decide("frozen", f"world/change {msg.get('kind', '')}: stopped, dropped {dropped} queued action(s), "
                                   "waiting for a new action")

    def on_permit(self, msg):
        """L1: a revoked move permit stops the Responder on that route; a re-earned one lifts the hold."""
        route = msg.get("route")
        if msg.get("granted"):
            self.revoked.discard(route)
            return
        self.revoked.add(route)
        if self.state == "moving" and self.route == route:
            dropped = len(self.queue)
            self.path, self.queue, self.state = [], [], "frozen"
            self._decide("frozen", f"move permit for {route} revoked ({msg.get('reason', '')}): stopped, "
                                   f"dropped {dropped} queued action(s)")

    def on_action(self, msg):
        """Run a responder/action now, or queue it behind the current move (the planner sends a whole
        move -> grip -> place_supply -> release sequence at once and there is no completion message)."""
        if self.state == "moving" or self.queue:
            self.queue.append(dict(msg))
            return self._decide("queued", f"{msg.get('action')} {msg.get('item')} waits for the current move "
                                          f"({len(self.queue)} queued)")
        return self._run(msg)

    def _drain(self):
        """Run queued actions in order until one starts a move (or one is refused, which clears the rest)."""
        while self.queue and self.state != "moving":
            out = self._run(self.queue.pop(0))
            if out["outcome"] == "refused" and self.queue:
                self._decide("refused", f"dropped {len(self.queue)} queued action(s) after a refusal")
                self.queue = []

    def _run(self, msg):
        action, item, route = msg.get("action"), msg.get("item"), msg.get("route")
        tag = f"{action} {item}"
        if action == "move":
            return self.move(route)
        if item not in SUPPLIES:
            return self._refuse(f"unknown item {item!r}", tag)
        if action == "grip":
            return self.grip_supply(item)
        if action in ("place_supply", "release"):
            return self.place_supply(item, tag)
        return self._refuse(f"unknown action {action!r}", tag)

    # ---- actions ----------------------------------------------------------------
    def move(self, route_id):
        tag = f"move {route_id}"
        cells = self.routes.get(route_id)
        if not cells:
            return self._refuse(f"no route/proposed with id {route_id!r}", tag)
        if route_id in self.revoked:
            return self._refuse(f"move permit for route {route_id} is revoked until a fresh scan", tag)
        if route_id in self.needs_gate and route_id not in self.approved:
            return self._refuse(f"route {route_id} is risky and has no approved gate/answer", tag)
        self.path = [cell_centre(c) for c in cells]
        self.route, self.state = route_id, "moving"
        return self._decide("act", f"following route {route_id}, {len(cells)} cells", tag)

    def grip_supply(self, item):
        tag = f"grip {item}"
        if self.holding(item):
            return self._decide("done", f"already carrying {item}", tag)
        if self._distance(item) > REACH:
            return self._refuse(f"{item} is {self._distance(item):.2f} m away, reach is {REACH} m", tag)
        self._hold(self._eq("carry_" + item), SLOTS[item])
        return self._decide("done", f"picked up {item}", tag)

    def place_supply(self, item, tag=None):
        tag = tag or f"place_supply {item}"
        if not self.holding(item):
            if tag.startswith("release"):     # e.g. the planner's release right after place_supply
                return self._decide("done", f"gripper open, not holding {item}", tag)
            return self._refuse(f"not carrying {item}", tag)
        if self.state == "moving":
            return self._refuse("still moving; place supplies only when stopped", tag)
        self.d.eq_active[self._eq("carry_" + item)] = 0
        if tag.startswith("place_supply"):
            # Set it down on the floor just in front of the gripper (toward the casualty), upright and still.
            fwd = np.array([math.cos(self.yaw), math.sin(self.yaw)])
            x, y = self._put_down(item, self.pos[:2] + fwd * (HALF_LEN + PLACE_AHEAD))
            return self._decide("done", f"placed {item} at [{x:.2f}, {y:.2f}]", tag)
        return self._decide("done", f"released {item}", tag)

    def _put_down(self, name, xy):
        """Lower free body `name` onto the floor at xy (upright, at rest); the gripper's last move."""
        body = self.m.body(name).id
        geom = self.m.body_geomadr[body]
        cylinder = self.m.geom_type[geom] == mujoco.mjtGeom.mjGEOM_CYLINDER
        half_z = float(self.m.geom_size[geom][1 if cylinder else 2])
        jnt = self.m.body_jntadr[body]
        adr, vadr = self.m.jnt_qposadr[jnt], self.m.jnt_dofadr[jnt]
        self.d.qpos[adr:adr + 7] = [xy[0], xy[1], half_z + 0.002, 1.0, 0.0, 0.0, 0.0]
        self.d.qvel[vadr:vadr + 6] = 0.0
        mujoco.mj_forward(self.m, self.d)
        return float(xy[0]), float(xy[1])

    def grip_block(self, block_id):
        """Clear light debris: hold block `block_id` above the deck. Refuses blocks of LIGHT_KG or more."""
        tag = f"grip {block_id}"
        try:
            body = self.m.body(block_id).id
        except KeyError:
            return self._refuse(f"no block {block_id!r}", tag)
        mass = float(self.m.body_mass[body])
        if mass >= LIGHT_KG:
            return self._refuse(f"{block_id} is {mass:.1f} kg; only blocks under {LIGHT_KG} kg can be cleared", tag)
        eq = self._eq("grip_" + block_id)
        if eq < 0:
            return self._refuse(f"{block_id} has no grip weld in the scene", tag)
        if self._distance(block_id) > REACH:
            return self._refuse(f"{block_id} is {self._distance(block_id):.2f} m away, reach is {REACH} m", tag)
        half_z = float(self.m.geom_size[self.m.body_geomadr[body]][2])
        self._hold(eq, (0.0, 0.0, BLOCK_SLOT_Z + half_z))
        return self._decide("done", f"gripped {block_id} ({mass:.1f} kg)", tag)

    def release_block(self, block_id):
        tag = f"release {block_id}"
        if not self.holding(block_id):
            return self._refuse(f"not holding {block_id}", tag)
        if self.state == "moving":
            return self._refuse("still moving; release blocks only when stopped", tag)
        self.d.eq_active[self._eq("grip_" + block_id)] = 0
        # Set it down beside the chassis on the left, off the route the Responder just cleared.
        body = self.m.body(block_id).id
        sx, sy, _ = self.m.geom_size[self.m.body_geomadr[body]]
        left = np.array([-math.sin(self.yaw), math.cos(self.yaw)])
        x, y = self._put_down(block_id, self.pos[:2] + left * (HALF_WIDTH + max(sx, sy) + 0.03))
        return self._decide("done", f"released {block_id} at [{x:.2f}, {y:.2f}]", tag)

    # ---- motion -----------------------------------------------------------------
    def free_ahead(self, heading, step):
        """True if no geom is within HALF_LEN + GAP + step ahead, on the centre line or either side."""
        fwd = np.array([math.cos(heading), math.sin(heading), 0.0])
        side = np.array([-fwd[1], fwd[0], 0.0])
        need = HALF_LEN + GAP + step
        geomid = np.zeros(1, dtype=np.int32)
        for z in RAY_HEIGHTS:
            for offset in (0.0, HALF_WIDTH, -HALF_WIDTH):
                origin = np.array([*self.pos[:2], z]) + side * offset
                dist = mujoco.mj_ray(self.m, self.d, origin, fwd, None, 1, self.body, geomid)
                if 0 <= dist < need and not self._carried_geom(int(geomid[0])):
                    return False
        return True

    def _carried_geom(self, geom):
        """Geoms the Responder itself carries never block it."""
        body = int(self.m.geom_bodyid[geom])
        name = mujoco.mj_id2name(self.m, mujoco.mjtObj.mjOBJ_BODY, body) or ""
        return self.holding(name) if (name in SUPPLIES or name.startswith("b")) else False

    def step(self, dt):
        """Advance along the current route by up to SPEED * dt; stop and report if a block is in the way."""
        if self.state != "moving":
            return
        if self.shaking():
            # Freeze at the first tick of the shake, not 3 s later when world/change arrives.
            dropped = len(self.queue)
            self.path, self.queue, self.state = [], [], "frozen"
            self._decide("frozen", f"aftershock shaking: stopped, dropped {dropped} queued action(s), "
                                   "waiting for a new action")
            return
        budget = SPEED * dt
        while self.path and budget > 1e-9:
            delta = self.path[0] - self.pos[:2]
            dist = float(np.linalg.norm(delta))
            if dist < ARRIVE:
                self.path.pop(0)
                continue
            heading = math.atan2(delta[1], delta[0])
            step = min(budget, dist)
            if not self.free_ahead(heading, step):
                self._set_pose(self.pos[:2], heading)
                dropped = len(self.queue)
                self.path, self.queue, self.state = [], [], "blocked"
                self._decide("blocked", f"collision ray: block ahead on route {self.route}, stopped"
                                        + (f", dropped {dropped} queued action(s)" if dropped else ""))
                return
            self._set_pose(self.pos[:2] + delta / dist * step, heading)
            budget -= step
        if not self.path:
            self.state = "arrived"
            self._decide("done", f"arrived at the end of route {self.route}", f"move {self.route}")
            self._drain()

    def status(self):
        x, y, _ = (round(float(v), 3) for v in self.pos)
        return {"state": self.state, "pos": [x, y], "yaw": round(self.yaw, 3), "route": self.route,
                "carrying": [n for n in SUPPLIES if self.holding(n)]}


def attach(world, bus):
    """Wire a Responder into a sim World and the hub Bus and return it.

    It has no task of its own: sim.run() calls `world.responder.step(dt)` on every tick, so the hub's
    shutdown (which cancels world.task) stops it too, and it never runs out of step with the physics.
    """
    pending = set()

    def publish(topic, data):
        task = asyncio.get_running_loop().create_task(bus.publish(topic, data))
        pending.add(task)
        task.add_done_callback(pending.discard)

    r = Responder(world.m, world.d, publish, clock=lambda: world.t, shaking=lambda: world.shaking)
    bus.subscribe("route/proposed", r.on_route)
    bus.subscribe("gate/request", r.on_gate_request)
    bus.subscribe("gate/answer", r.on_gate_answer)
    bus.subscribe("responder/action", r.on_action)
    bus.subscribe("world/change", r.on_world_change)
    bus.subscribe("permit/route", r.on_permit)
    return r
