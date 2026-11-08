"""Real-lane end-to-end rescue run (#31): every lane real, on the hub's own Bus, nothing faked.

    GEMINI_MODE=off python tools/run_rescue.py --auto-approve          # ground rescue + shift
    GEMINI_MODE=off python tools/run_rescue.py --auto-approve --b1     # then the L4 B1 descent

Lanes: sim, perception, planner and voice are imported and started with `start(bus)` exactly as the
hub does, on coord.hub.Bus (every payload validated). The runner only (1) answers gate/request when
--auto-approve is given (tests only; the demo uses the console), (2) drops the sim's spare block onto
the Responder's route ahead of it, where the Scout can see it if any such cell exists (the unscripted
change, as POST /inject does), (3) types the report
command at the end, and (4) samples the real Scout and Responder poses from the sim object, read
only, every POSE_EVERY seconds.

Steps checked, in order: scene loaded, casualty found, route verified, move permit granted,
Responder moving; then the shift: block landed, permit revoked by what the robots sensed, the
Responder stopped and stays stopped; then the fresh recheck: a permit granted again (the same route
re-earned, or a new verified route that avoids the block), the Responder moving again, the supply
placed by the casualty, the handover report. --b1 adds the L4 descent (sim.demo_descent, #114),
which is not on the hub: it runs only if that module is installed and is logged as its own stage.

runs/rescue-<seed>.jsonl gets every bus message as {"t","topic","data"} (a message the hub rejected
carries "rejected"), plus runner records whose topic starts with "_": _probe/pose (sampled poses),
_runner/step (each check, ok or FAIL, with what was seen), _runner/action (what the runner did) and
_runner/summary. Exit 0 only if every step passed.
"""

import argparse
import asyncio
import importlib
import json
import math
import os
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LANES = ("voice", "planner", "perception", "sim")    # consumers first: sim publishes scene/loaded on start
POSE_EVERY = 0.5
RES = 0.05
SHIFT_AHEAD = 0.5      # metres ahead of the Responder along its route where the block is dropped
STILL = 0.01           # metres: a stopped Responder moves less than this while it stays stopped
NEAR_CASUALTY = 0.5    # metres: a supply placed this close to the casualty counts as delivered


class Recorder:
    """Logs every bus message (validated first, as the hub does) and the runner's own records."""

    def __init__(self, bus, path):
        from coord.messages import validate_payload

        self.f = open(path, "w", encoding="utf-8")  # noqa: SIM115 (closed in main)
        self.t0 = time.monotonic()
        self.seen = []
        self.waiters = []
        publish = bus.publish

        async def logged(topic, data):
            entry = {"t": self.now(), "topic": topic, "data": data}
            try:
                validate_payload(topic, data)
            except ValueError as e:
                entry["rejected"] = str(e).splitlines()[0]
                self._write(entry)
                raise
            if topic != "sensors/scout":          # 10 Hz raw frames: counted, not stored
                self._write(entry)
            self.seen.append((entry["t"], topic, data))
            for w in tuple(self.waiters):
                if w[0] == topic and w[1](data) and not w[2].done():
                    w[2].set_result(data)
            await publish(topic, data)

        bus.publish = logged
        self.results = []

    def now(self):
        return round(time.monotonic() - self.t0, 2)

    def _write(self, entry):
        if self.f.closed:          # sim tasks may still publish after the run ends
            return
        self.f.write(json.dumps(entry, allow_nan=False) + "\n")
        self.f.flush()

    def note(self, topic, data):
        self._write({"t": self.now(), "topic": topic, "data": data})

    def step(self, name, ok, detail):
        self.results.append((name, ok))
        self.note("_runner/step", {"step": name, "ok": ok, "detail": detail})
        print(f"  {'ok  ' if ok else 'FAIL'} {self.now():7.1f}s  {name}: {detail}")
        return ok

    async def expect(self, name, topic, pred=lambda d: True, since=0.0, timeout=60.0, show=None):
        """Wait for a message on topic matching pred, at or after time `since` (seconds into the run)."""
        for t, tp, d in self.seen:
            if tp == topic and t >= since and pred(d):
                self.step(name, True, show(d) if show else topic)
                return d
        fut = asyncio.get_running_loop().create_future()
        w = (topic, pred, fut)
        self.waiters.append(w)
        try:
            d = await asyncio.wait_for(fut, timeout)
        except TimeoutError:
            self.step(name, False, f"no matching {topic} within {timeout:.0f} s")
            return None
        finally:
            self.waiters.remove(w)
        self.step(name, True, show(d) if show else topic)
        return d


def poses(world):
    r = getattr(world, "responder", None)
    out = {"scout": [round(float(v), 3) for v in world.pos],
           "scout_state": world.state}
    if r is not None:
        out.update(responder=[round(float(v), 3) for v in r.pos], responder_state=r.state,
                   responder_route=getattr(r, "route", None))
    return out


def in_scout_view(world, cell, max_range=4.0):
    """True if a LiDAR-height ray from the Scout reaches the centre of `cell` unobstructed (sim object,
    read only): only then can the Scout sense a shift there."""
    import numpy as np

    from sim import sensors

    origin = np.asarray(world.pos, float)
    target = np.array([(cell[0] + 0.5) * RES, (cell[1] + 0.5) * RES, origin[2]])
    dist = float(np.linalg.norm(target - origin))
    if dist > max_range or dist < 1e-6:
        return False
    hit, _ = sensors._ray(world.m, world.d, origin, (target - origin) / dist, world.scout, sensors.SENSE_GROUPS)
    return hit < 0 or hit >= dist - RES


def shift_cell(route, responder_xy, ahead=SHIFT_AHEAD, visible=None):
    """(cell, in_view): the first route cell at least `ahead` m past the cell nearest the Responder,
    preferring one `visible(cell)` accepts; falls back to the first such cell if none is visible."""
    cells = route["cells"]
    centre = [((c[0] + 0.5) * RES, (c[1] + 0.5) * RES) for c in cells]
    near = min(range(len(cells)), key=lambda n: math.dist(centre[n], responder_xy))
    run, first = 0.0, None
    for n in range(near + 1, len(cells) - 3):       # never on the last cells (the goal beside c1)
        run += math.dist(centre[n - 1], centre[n])
        if run < ahead:
            continue
        first = first or cells[n]
        if visible is None or visible(cells[n]):
            return cells[n], visible is not None
    return first, False


async def ground_rescue(rec, bus, world, args):
    since = 0.0
    if not await rec.expect("scene loaded", "scene/loaded", timeout=30,
                            show=lambda d: f"scene {d['scene']}, {len(d['blocks'])} blocks"):
        return
    cas = await rec.expect("casualty found", "map/casualties", lambda d: len(d) > 0, timeout=args.find_timeout,
                           show=lambda d: f"{d[0]['id']} at {d[0]['pos']} conf {d[0]['confidence']}")
    if not cas:
        return
    route = await rec.expect("route proposed", "route/proposed", timeout=60,
                             show=lambda d: f"{d['id']}, {len(d['cells'])} cells, model {d['model']}")
    if not route:
        return
    rid = route["id"]
    if not await rec.expect("route verified by physics", "route/verified", lambda d: d["id"] == rid and d["ok"],
                            timeout=30, show=lambda d: d["detail"]):
        return
    if not await rec.expect("move permit granted", "permit/route",
                            lambda d: d["route"] == rid and d["granted"], timeout=30,
                            show=lambda d: d["reason"]):
        return

    # Let the Responder get going on that route before the shift.
    r = world.responder
    t_end = time.monotonic() + 60
    start_xy = None
    while time.monotonic() < t_end:
        if r.state == "moving" and r.route == rid:
            start_xy = start_xy or [float(v) for v in r.pos[:2]]
            if math.dist(start_xy, r.pos[:2]) >= args.drive_before:
                break
        await asyncio.sleep(0.1)
    moving = r.state == "moving" and start_xy is not None
    rec.step("Responder moving on the route", moving,
             f"state {r.state} on {r.route}, {math.dist(start_xy or r.pos[:2], r.pos[:2]):.2f} m driven")
    if not moving:
        return

    # The shift: the spare block lands on the route ahead of the Responder.
    cell, seen = shift_cell(route, r.pos[:2], visible=None if args.shift == "ahead"
                            else (lambda c: in_scout_view(world, c)))
    if cell is None:
        rec.step("shift placed", False, "less than SHIFT_AHEAD of route left ahead of the Responder")
        return
    since = rec.now()
    name = world.inject(cell)
    rec.note("_runner/action", {"action": "inject", "cell": cell, "block": name, "in_scout_view": seen,
                                "scout": [round(float(v), 3) for v in world.pos],
                                "responder": [round(float(v), 3) for v in r.pos]})
    print(f"  ..  {since:7.1f}s  dropped {name} on route {rid} at cell {cell} "
          f"({'in' if seen else 'NOT in'} the Scout's line of sight)")
    await rec.expect("block landed (world/change)", "world/change", since=since, timeout=10,
                     show=lambda d: f"{d['kind']} {d['moved_blocks']}")
    revoked = await rec.expect("permit revoked by sensed change", "permit/route",
                               lambda d: d["route"] == rid and not d["granted"], since=since, timeout=20,
                               show=lambda d: f"{d['reason']} | evidence: "
                                              + ", ".join(e["kind"] for e in d["evidence"]))
    stop_t = time.monotonic() + 5
    # Stopped means no longer driving the revoked route: it may already follow a re-planned one.
    while time.monotonic() < stop_t and r.state == "moving" and r.route == rid:
        await asyncio.sleep(0.1)
    held = [float(v) for v in r.pos[:2]]
    rec.step("Responder stopped on the revoked route", not (r.state == "moving" and r.route == rid),
             f"state {r.state} on {r.route} at {[round(v, 2) for v in held]}")
    await asyncio.sleep(2.0)
    drift = math.dist(held, r.pos[:2])
    rec.step("Responder stays stopped", drift < STILL or r.route != rid,
             f"moved {drift:.3f} m in 2 s (state {r.state}, route {r.route})")

    # The fresh recheck: a permit granted again after the revocation.
    # Count any grant after the revocation itself: a re-plan can be granted while the stop is checked.
    since2 = next((t for t, tp, d in rec.seen if tp == "permit/route" and d is revoked), since)
    granted = await rec.expect("permit granted again after a fresh check", "permit/route",
                               lambda d: d["granted"], since=since2, timeout=args.recheck_timeout,
                               show=lambda d: f"{d['route']}: {d['reason']} | evidence: "
                                              + ", ".join(e["kind"] for e in d["evidence"]))
    if not granted:
        return
    new = next((d for t, tp, d in reversed(rec.seen) if tp == "route/proposed" and d["id"] == granted["route"]), route)
    on_block = [c for c in new["cells"] if c[:2] == cell[:2]]
    rec.step("route after the recheck avoids the block", not on_block,
             f"{new['id']} ({'same route' if new['id'] == rid else 're-planned'}), "
             f"{len(new['cells'])} cells, {'passes' if on_block else 'avoids'} cell {cell[:2]}")
    t_end = time.monotonic() + 30
    while time.monotonic() < t_end and not (r.state == "moving" and r.route == new["id"]):
        await asyncio.sleep(0.1)
    rec.step("Responder moving again", r.state in ("moving", "arrived") or r.route == new["id"],
             f"state {r.state} on {r.route}")
    cpos = cas[0]["pos"][:2]
    await rec.expect(f"supply placed within {NEAR_CASUALTY} m of the casualty", "log/decision",
                     lambda d: placed_at(d) is not None and math.dist(placed_at(d), cpos) <= NEAR_CASUALTY,
                     since=since2, timeout=args.deliver_timeout, show=lambda d: d["reason"])
    mark = rec.now()
    await bus.publish("operator/command", {"text": "handover report", "source": "typed"})
    rec.note("_runner/action", {"action": "operator/command", "text": "handover report"})
    await rec.expect("handover report", "report/handover", since=mark, timeout=30,
                     show=lambda d: f"{len(d.get('markdown', ''))} chars of markdown")


def placed_at(d):
    """(x, y) of a Responder 'placed <item> at [x, y]' log/decision, else None."""
    if d.get("outcome") != "done" or not d.get("reason", "").startswith("placed "):
        return None
    m = re.search(r"at \[(-?[\d.]+), (-?[\d.]+)\]", d["reason"])
    return (float(m[1]), float(m[2])) if m else None


def stray_placements(rec):
    """Supplies placed more than NEAR_CASUALTY from every casualty perception reported: a finding."""
    casualties = [c["pos"][:2] for t, tp, d in rec.seen if tp == "map/casualties" for c in d]
    out = []
    for t, tp, d in rec.seen:
        xy = placed_at(d) if tp == "log/decision" else None
        if xy and casualties and min(math.dist(xy, c) for c in casualties) > NEAR_CASUALTY:
            out.append({"t": t, "reason": d["reason"]})
    if out:
        rec.note("_runner/finding", {"placed_away_from_casualties": out})
        print(f"  !!  supply placed away from every casualty: {[o['reason'] for o in out]}")
    return out


def b1_descent(rec, args):
    try:
        demo = importlib.import_module("sim.demo_descent")
    except ModuleNotFoundError:
        rec.note("_runner/stage", {"stage": "b1", "skipped": "sim.demo_descent not installed (L4, PR #114)"})
        rec.step("B1 descent", False, "skipped: sim.demo_descent is not on this branch (L4, PR #114)")
        return
    out = demo.run(max_t=args.b1_time)
    for row in out.get("trail", []):
        rec.note("_probe/b1_cell", {"cell": row})
    rec.note("_runner/stage", {"stage": "b1", **{k: v for k, v in out.items() if k not in ("map", "trail", "log")}})
    rec.step("B1 descent (L4, not on the hub)", out["reached"] and out["levels"] == ["L1", "ground", "B1"],
             f"levels {out['levels']}, max move/tick {out['max_jump']} m, responder route {out['responder_route']} "
             f"k {out['route_k']}")


async def main(args):
    os.environ.setdefault("GEMINI_MODE", "off")
    from coord.hub import Bus

    runs = ROOT / "runs"
    runs.mkdir(exist_ok=True)
    bus = Bus()
    rec = Recorder(bus, runs / f"rescue-{args.seed}.jsonl")
    print(f"log: {rec.f.name}  (GEMINI_MODE={os.environ['GEMINI_MODE']}, every lane real)")

    async def answer(req):
        yes = True
        if not args.auto_approve:
            line = await asyncio.get_running_loop().run_in_executor(
                None, input, f"  approve {req['kind']}: {req['summary']}? [y/n] ")
            yes = line.strip().lower().startswith("y")
        await bus.publish("gate/answer", {"id": req["id"], "approved": yes, "by": "operator"})
        rec.note("_runner/action", {"action": "gate/answer", "id": req["id"], "approved": yes,
                                    "auto": args.auto_approve})

    def on_request(req):
        asyncio.ensure_future(answer(req))

    bus.subscribe("gate/request", on_request)
    started = {}
    for lane in LANES:
        mod = importlib.import_module(lane)
        res = mod.start(bus)
        started[lane] = await res if asyncio.iscoroutine(res) else res
    world = started["sim"]

    async def sample():
        while True:
            rec.note("_probe/pose", poses(world))
            await asyncio.sleep(POSE_EVERY)

    sampler = asyncio.ensure_future(sample())
    try:
        await ground_rescue(rec, bus, world, args)
        stray_placements(rec)
    finally:
        sampler.cancel()
        task = getattr(world, "task", None)
        if task:
            task.cancel()
    if args.b1:
        b1_descent(rec, args)
    failed = [n for n, ok in rec.results if not ok]
    counts = {}
    for _, tp, _ in rec.seen:
        counts[tp] = counts.get(tp, 0) + 1
    rec.note("_runner/summary", {"passed": len(rec.results) - len(failed), "failed": failed, "messages": counts})
    rec.f.close()
    print(f"{len(rec.results) - len(failed)}/{len(rec.results)} steps passed"
          + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 0 if not failed and rec.results else 1


def parse(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--seed", type=int, default=7, help="names the log file (the backup scene is fixed)")
    p.add_argument("--auto-approve", action="store_true", help="answer every gate/request yes (tests only)")
    p.add_argument("--b1", action="store_true", help="also run the L4 descent to B1 (needs PR #114)")
    p.add_argument("--find-timeout", type=float, default=180.0, help="seconds to find the casualty")
    p.add_argument("--recheck-timeout", type=float, default=120.0, help="seconds for the fresh recheck")
    p.add_argument("--deliver-timeout", type=float, default=180.0, help="seconds to place the supply")
    p.add_argument("--drive-before", type=float, default=0.3, help="metres driven before the shift")
    p.add_argument("--shift", choices=("visible", "ahead"), default="visible",
                   help="drop the block where the Scout can see it (default), or just ahead of the Responder")
    p.add_argument("--b1-time", type=float, default=400.0, help="sim seconds allowed for the B1 descent")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse())))
