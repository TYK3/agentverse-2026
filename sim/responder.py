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
                         running are queued and run in order when it ends (there is no completion message).
                         Y2: with `block`, grip/release act on that block (release sets debris aside, off
                         the route) and place_supply sets a held block down in front, toward the casualty
                         (found material, e.g. a board used as a splint)
- in  `world/change`     freeze in place, drop the current move and the queue (wait for a new responder/action)
- in  `permit/route`     L1: granted false stops a move on that route at once and refuses new moves on it
                         until a granted true arrives (routes with no permit message behave as before)
- out `log/decision`     every action's outcome; refusals say outcome "refused" and why. When the collision
                         ray stops a move, a `ray_hit` record comes first (just before "blocked"): perception
                         "responder ray hit at [x, y], cell [i, j, k]", reason "robot responder route <id> hit
                         <geom> at [x, y] cell [i, j, k]" (the nearest ray hit, scene frame; cell = floor(pos / RES),
                         k from the route), so the planner can mark the blocked cell

Clearing debris is `grip_block(block_id)` / `release_block(block_id)`, reached from responder/action's
optional `block` (Y2). Two mass limits: a block slid aside to clear a route may be up to LIGHT_KG; a block
carried to a casualty (place_supply) must be within the arm's payload, ARM_PAYLOAD_KG (Kinova Gen3 lite,
0.5 kg, docs/hardware.md).
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
RAY_HEIGHTS = (0.03, 0.09)  # collision ray heights above the floor under the Responder (low rubble and wall height)
RIDE_Z = 0.05               # chassis centre above the floor (backup.xml and levels.xml)
PROBE = 0.25                # the floor ray starts this far above the current floor (under any slab above)
MAX_RISE = 0.6              # max floor change per metre driven (as sim/levels.py); a bigger change is a drop, ignored
STEP_SLACK = 0.004          # metres of floor change always allowed per step (ramp seams, float noise)
ARRIVE = 0.005              # metres
SKIP_NEAR = RES             # a route's leading waypoints closer than this are skipped, not turned to (B4-WALL-STOP)
REACH = 0.45                # a supply or block further than this from the Responder centre cannot be gripped
LIGHT_KG = 2.0              # blocks at or above this mass are too heavy to clear
ARM_PAYLOAD_KG = 0.5        # found material carried to a casualty: the real arm's rated payload (docs/hardware.md)
SUPPLIES = ("water", "first_aid_kit", "radio", "bandage", "splint", "thermal_blanket")
FOUND_USES = ("splint",)    # kit items a found block can stand in for: gripping one for this is a carry
RISKY_KINDS = ("risky_move", "enter_at_risk")

# Held poses in the Responder frame: supplies sit in deck slots, a gripped block is lifted above them.
SLOTS = {"water": (-0.1, 0.0, 0.11), "first_aid_kit": (0.0, 0.0, 0.08), "radio": (0.1, 0.0, 0.095),
         # Y2 kit, stacked: blanket on the first aid kit, splint on the blanket, bandage on the radio
         "thermal_blanket": (0.0, 0.0, 0.122), "splint": (0.0, 0.0, 0.137), "bandage": (0.1, 0.0, 0.156)}
BLOCK_SLOT_Z = 0.18         # above the tallest supply (water top is 0.17 over the Responder centre); add the block's half height
PLACE_AHEAD = 0.08          # place_supply sets the item down this far in front of the chassis
# KIT-SPOTS (#262): later items go beside earlier ones, not on them. Spots ahead of the gripper, nearest
# first: centre, then PLACE_SIDE and twice that to each side, then a second row PLACE_ROW further out.
PLACE_SIDE = 0.10           # metres between spots across the Responder's heading
PLACE_ROW = 0.12            # metres between the two rows of spots
PLACE_GAP = 0.02            # metres kept clear between a set-down item and any supply already on the floor


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
        self.failed_routes = set()  # routes whose move was refused: their other actions are refused too
        self.log = []              # every log/decision this Responder published
        self.last_hit = None       # nearest blocking ray hit of the last free_ahead: (x, y), geom name
        self.floor_z = float(self.pos[2]) - RIDE_Z   # floor under the chassis; follows ramps (levels.xml)
        self.pitch = 0.0           # nose-down tilt in radians, from the floor under the front and back

    # ---- pose -------------------------------------------------------------------
    @property
    def pos(self):
        return self.d.mocap_pos[self.mocap].copy()

    @property
    def yaw(self):
        w, _, _, z = self.d.mocap_quat[self.mocap]
        return 2.0 * math.atan2(z, w)

    def _set_pose(self, xy, yaw):
        """Put the chassis at (x, y) facing yaw, riding the floor under it: z follows the floor (ramps
        between levels) and pitch follows the slope between the floor under the front and the back."""
        xy = np.asarray(xy, float)
        self.floor_z = self._follow(xy, self.floor_z, float(np.linalg.norm(xy - self.pos[:2])))
        fwd = np.array([math.cos(yaw), math.sin(yaw)])
        front = self._follow(xy + fwd * HALF_LEN, self.floor_z, HALF_LEN)
        back = self._follow(xy - fwd * HALF_LEN, self.floor_z, HALF_LEN)
        self.pitch = math.atan2(back - front, 2 * HALF_LEN)
        self.d.mocap_pos[self.mocap] = [xy[0], xy[1], self.floor_z + RIDE_Z]
        cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
        cp, sp = math.cos(self.pitch / 2), math.sin(self.pitch / 2)
        self.d.mocap_quat[self.mocap] = [cy * cp, -sy * sp, cy * sp, sy * cp]   # yaw about z, then pitch about y

    def _floor_at(self, xy, z_from):
        """Height of the first surface below (x, y) from z_from, skipping the Responder and what it carries."""
        geomid = np.zeros(1, dtype=np.int32)
        z = z_from
        for _ in range(8):
            dist = mujoco.mj_ray(self.m, self.d, np.array([xy[0], xy[1], z]), np.array([0.0, 0.0, -1.0]),
                                 None, 1, self.body, geomid)
            if dist < 0:
                return None
            if not self._carried_geom(int(geomid[0])):
                return z - dist
            z -= dist + 1e-4
        return None

    def _follow(self, xy, floor, run):
        """Floor height at xy if it is reachable from `floor` over `run` metres (a ramp), else `floor`:
        a drop or a wall top is not driven onto, and with no floor below (a bare plane scene) nothing changes."""
        z = self._floor_at(xy, floor + PROBE)
        if z is None or abs(z - floor) > MAX_RISE * run + STEP_SLACK:
            return floor
        return z

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
        # A re-plan supersedes the old mission, rather than waiting behind its move.
        # Validate it first: a refused replacement must leave the current move intact.
        if (msg.get("action") == "move" and msg.get("route") != self.route
                and (self.state == "moving" or self.queue)):
            old_route, dropped = self.route, len(self.queue)
            result = self._run(msg)
            if result["outcome"] != "refused":
                self.queue = []
                self._decide("replaced", f"route {old_route} replaced by {self.route}; "
                                         f"dropped {dropped} obsolete queued action(s)")
            return result
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
            out = self.move(route)
            if out["outcome"] == "refused":
                self.failed_routes.add(route)
            else:
                self.failed_routes.discard(route)
            return out
        if route in self.failed_routes:
            # Never place or drop a supply where the Responder did not drive (its move was refused).
            return self._refuse(f"move on route {route} was refused; {action} {item} not done", tag)
        block = msg.get("block")
        if block:
            return self._run_block(action, block, item)
        if item not in SUPPLIES:
            return self._refuse(f"unknown item {item!r}", tag)
        if self._eq("carry_" + item) < 0:
            return self._refuse(f"{item} is not loaded in this scene's kit", tag)
        if action == "grip":
            return self.grip_supply(item)
        if action in ("place_supply", "release"):
            return self.place_supply(item, tag)
        return self._refuse(f"unknown action {action!r}", tag)

    def _run_block(self, action, block, item=None):
        """Y2: grip / release / place_supply on a named block. A grip whose `item` is one a block can stand
        in for (FOUND_USES, e.g. splint) is found material for a casualty, so it must fit the arm's
        payload; any other item (the contract always names one) means the block is debris to clear."""
        carry = item in FOUND_USES
        if action == "grip":
            return self.grip_block(block, carry=carry)
        if action == "release":
            if carry and self._eq("grip_" + block) >= 0 and not self.holding(block):   # release after place_supply
                return self._decide("done", f"gripper open, not holding {block}", f"release {block}")
            return self.release_block(block)
        if action == "place_supply":
            return self.place_block(block, item)
        return self._refuse(f"unknown action {action!r}", f"{action} {block}")

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
        self.path = self._start_path(cells)
        self.route, self.state = route_id, "moving"
        return self._decide("act", f"following route {route_id}, {len(cells)} cells", tag)

    def _start_path(self, cells):
        """Waypoints for a move along `cells`, starting from where the Responder is parked.

        A replan's first cell is the one the Responder is parked in, its centre a few cm off the pose.
        Turning to face that centre, or cutting across to the route's line, angles the chassis and can
        swing a side ray into a wall the route runs beside (B4-WALL-STOP: parked at [-0.49, -1.24], route
        north at x -0.475, b4's end at x -0.40). So when the pose is within SKIP_NEAR of the first centre,
        the first straight run is shifted sideways onto the pose (less than a cell, inside the planned
        corridor) and driven parallel to the route; the turn at its end takes the offset up.
        """
        path = [cell_centre(c) for c in cells]
        here = self.pos[:2]
        if len(path) < 2 or float(np.linalg.norm(path[0] - here)) >= SKIP_NEAR:
            return path
        d = path[1] - path[0]
        d = d / float(np.linalg.norm(d))
        off = here - path[0]
        off = off - d * float(off @ d)              # sideways part only
        run = 2
        while run < len(path):
            v = path[run] - path[0]
            if abs(v[0] * d[1] - v[1] * d[0]) > 1e-6 or float(v @ d) <= 0:
                break
            run += 1
        return [p + off for p in path[1:run]] + path[run:]

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
            x, y = self._put_down(item, self._free_spot(item))
            return self._decide("done", f"placed {item} at [{x:.2f}, {y:.2f}]", tag)
        return self._decide("done", f"released {item}", tag)

    def _footprint(self, name):
        """Radius (m) of body `name`'s footprint on the floor: a cylinder's radius, a box's half diagonal."""
        geom = self.m.body_geomadr[self.m.body(name).id]
        size = self.m.geom_size[geom]
        if self.m.geom_type[geom] == mujoco.mjtGeom.mjGEOM_CYLINDER:
            return float(size[0])
        return float(math.hypot(size[0], size[1]))

    def _free_spot(self, item):
        """Where to set `item` down: the nearest spot ahead of the gripper clear of every supply already on the
        floor (not held), so a later item never lands on an earlier one (KIT-SPOTS, #262). The first item goes
        straight ahead, as before. If every spot is taken, straight ahead."""
        fwd = np.array([math.cos(self.yaw), math.sin(self.yaw)])
        side = np.array([-fwd[1], fwd[0]])
        ahead = self.pos[:2] + fwd * (HALF_LEN + PLACE_AHEAD)
        down = [(self.d.xpos[self.m.body(n).id][:2].copy(), self._footprint(n))
                for n in SUPPLIES if n != item and not self.holding(n) and self._has_body(n)]
        r = self._footprint(item)
        for row in (0.0, PLACE_ROW):
            for k in (0, 1, -1, 2, -2):
                xy = ahead + fwd * row + side * (k * PLACE_SIDE)
                if all(np.linalg.norm(xy - p) >= r + q + PLACE_GAP for p, q in down):
                    return xy
        return ahead

    def _has_body(self, name):
        try:
            self.m.body(name)
        except KeyError:
            return False
        return True

    def _put_down(self, name, xy):
        """Lower free body `name` onto the floor at xy (upright, at rest); the gripper's last move."""
        body = self.m.body(name).id
        geom = self.m.body_geomadr[body]
        cylinder = self.m.geom_type[geom] == mujoco.mjtGeom.mjGEOM_CYLINDER
        half_z = float(self.m.geom_size[geom][1 if cylinder else 2])
        jnt = self.m.body_jntadr[body]
        adr, vadr = self.m.jnt_qposadr[jnt], self.m.jnt_dofadr[jnt]
        self.d.qpos[adr:adr + 7] = [xy[0], xy[1], self.floor_z + half_z + 0.002, 1.0, 0.0, 0.0, 0.0]
        self.d.qvel[vadr:vadr + 6] = 0.0
        mujoco.mj_forward(self.m, self.d)
        return float(xy[0]), float(xy[1])

    def grip_block(self, block_id, carry=False):
        """Hold block `block_id` above the deck. To clear debris it must be under LIGHT_KG; to carry it to
        a casualty (`carry`, found material) it must be within ARM_PAYLOAD_KG."""
        tag = f"grip {block_id}"
        try:
            body = self.m.body(block_id).id
        except KeyError:
            return self._refuse(f"no block {block_id!r}", tag)
        mass = float(self.m.body_mass[body])
        if carry and mass > ARM_PAYLOAD_KG:
            return self._refuse(f"{block_id} is {mass:.2f} kg; the arm carries at most {ARM_PAYLOAD_KG} kg", tag)
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

    def place_block(self, block_id, item=None):
        """Y2: set a held block down in front of the gripper, toward the casualty (found material)."""
        tag = f"place_supply {block_id}"
        if not self.holding(block_id):
            return self._refuse(f"not holding {block_id}", tag)
        if self.state == "moving":
            return self._refuse("still moving; place supplies only when stopped", tag)
        self.d.eq_active[self._eq("grip_" + block_id)] = 0
        body = self.m.body(block_id).id
        reach = float(max(self.m.geom_size[self.m.body_geomadr[body]][:2]))
        fwd = np.array([math.cos(self.yaw), math.sin(self.yaw)])
        x, y = self._put_down(block_id, self.pos[:2] + fwd * (HALF_LEN + PLACE_AHEAD + reach))
        use = f" as a {item.replace('_', ' ')}" if item in FOUND_USES else ""
        return self._decide("done", f"placed {block_id}{use} at [{x:.2f}, {y:.2f}]", tag)

    # ---- motion -----------------------------------------------------------------
    def free_ahead(self, heading, step):
        """True if no geom is within HALF_LEN + GAP + step ahead, on the centre line or either side.

        Each ray rides the ground under its own start and end point (#267's _follow), so on a ramp it is
        tilted both ways, along the heading (pitch) and across it (roll, when crossing a slope at an
        angle), and the ramp surface never reads as a block. A floor change steeper than MAX_RISE (a
        wall, a drop) is not followed, so the ray stays level and a wall ahead still blocks.
        """
        h = np.array([math.cos(heading), math.sin(heading)])
        side = np.array([-h[1], h[0]])
        need = HALF_LEN + GAP + step
        geomid = np.zeros(1, dtype=np.int32)
        nearest = None
        for offset in (0.0, HALF_WIDTH, -HALF_WIDTH):
            p0 = self.pos[:2] + side * offset
            p1 = p0 + h * need
            f0 = self._follow(p0, self.floor_z, max(abs(offset), 1e-3))
            f1 = self._follow(p1, f0, need)
            for z in RAY_HEIGHTS:
                a = np.array([p0[0], p0[1], f0 + z])
                d = np.array([p1[0], p1[1], f1 + z]) - a
                length = float(np.linalg.norm(d))
                u = d / length
                dist = mujoco.mj_ray(self.m, self.d, a, u, None, 1, self.body, geomid)
                if (0 <= dist < length and not self._carried_geom(int(geomid[0]))
                        and (nearest is None or dist < nearest[0])):
                    nearest = (dist, a + u * dist, int(geomid[0]))
        if nearest is None:
            self.last_hit = None
            return True
        _, point, geom = nearest
        self.last_hit = ((float(point[0]), float(point[1])),
                         mujoco.mj_id2name(self.m, mujoco.mjtObj.mjOBJ_GEOM, geom) or f"geom{geom}")
        return False

    def _hit_cell(self, xy):
        """Grid cell of a scene-frame (x, y), as perception's map: floor(pos / RES); k from the current route."""
        cells = self.routes.get(self.route) or []
        k = 0
        if cells:
            near = min(cells, key=lambda c: float(np.linalg.norm(cell_centre(c) - np.asarray(xy))))
            k = int(near[2]) if len(near) > 2 else 0
        return [math.floor(xy[0] / RES), math.floor(xy[1] / RES), k]

    def _report_hit(self):
        """Publish where the collision ray hit (log/decision outcome "ray_hit"), before the "blocked" record."""
        if self.last_hit is None:
            return None
        (hx, hy), geom = self.last_hit
        # Cell from the same rounded point the record prints, so a hit on a cell edge (a wall face at
        # x = -0.05) reads back to the cell it names.
        hx, hy = round(hx, 3), round(hy, 3)
        i, j, k = self._hit_cell((hx, hy))
        data = {
            "t": round(max(0.0, float(self.clock())), 2),
            "perception": f"responder ray hit at [{hx:.3f}, {hy:.3f}], cell [{i}, {j}, {k}]",
            "model": "sim",
            "physics": "mujoco",
            "outcome": "ray_hit",
            "reason": f"robot responder route {self.route} hit {geom} at [{hx:.3f}, {hy:.3f}] cell [{i}, {j}, {k}]",
        }
        self.log.append(data)
        self.publish("log/decision", data)
        return data

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
                self._report_hit()
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

    def pose_message(self, t):
        """E2: the responder/pose payload, the Responder's actual pose this tick (sim.run publishes it at
        10 Hz, so viewers draw its real, continuous motion instead of jumping to the route's end)."""
        return {"t": round(max(0.0, float(t)), 2), "pos": [round(float(v), 3) for v in self.pos],
                "yaw": round(self.yaw, 3), "state": self.state, "route": self.route,
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
