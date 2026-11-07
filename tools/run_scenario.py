"""Drive the AFTERSHOCK scenario end to end on one in-process bus (T23, issue #31).

    python tools/run_scenario.py --seed 7 --auto-approve            # every lane faked
    python tools/run_scenario.py --seed 7 --real sim,planner        # swap in merged lanes
    GEMINI_MODE=live python tools/run_scenario.py --seed 7 --require-live

Path: scene load, Scout explores, casualty found, route proposed, verified, human approves, the
Responder starts, the aftershock fires, re-plan, (unscripted block injected, re-plan), delivery,
report. Every message is logged to runs/<seed>.jsonl (gitignored). Exit 0 only if every milestone
happened in order; 1 if one timed out; 2 if --require-live found a stand-in.

Lanes listed in --real are imported and started with `await <lane>.start(bus)` (the hub's rule);
the rest run from tools/scenario_fakes.py and count as stand-ins. A real sim must expose
`trigger_aftershock()` and `inject(cell)`, plain or async, on the object its start(bus) returns
(for example sim.World) or on the sim module.
"""

import argparse
import asyncio
import importlib
import inspect
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

fakes = importlib.import_module("scenario_fakes")

LANES = ("sim", "perception", "planner", "voice")


class LocalBus:
    """Same surface as coord.hub.Bus (subscribe, async publish), without payload validation."""

    def __init__(self):
        self.subs = {}

    def subscribe(self, topic, fn):
        self.subs.setdefault(topic, []).append(fn)

    async def publish(self, topic, data):
        for fn in tuple(self.subs.get(topic, ())):
            r = fn(data)
            if inspect.isawaitable(r):
                await r


def make_bus():
    """The hub's validating Bus when coord.hub is installed, so fakes are checked too."""
    try:
        from coord.hub import Bus
        return Bus(), "coord.hub.Bus (validated)"
    except ImportError:
        return LocalBus(), "LocalBus (coord.hub not installed, payloads not validated)"


async def call(fn, *args):
    r = fn(*args)
    return await r if inspect.isawaitable(r) else r


class Run:
    def __init__(self, bus, log_path, timeout):
        self.bus, self.timeout = bus, timeout
        self.log = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 (closed in main)
        self.t0 = time.monotonic()
        self.seen = []  # (topic, data) in order
        self.waiters = []
        self.gemini = None
        publish = bus.publish

        async def logged(topic, data):
            self.log.write(json.dumps({"t": round(time.monotonic() - self.t0, 3), "topic": topic,
                                       "data": data}) + "\n")
            self.seen.append((topic, data))
            if topic == "status/gemini":
                self.gemini = data
            for w in tuple(self.waiters):
                if w[0] == topic and w[1](data) and not w[2].done():
                    w[2].set_result(data)
            await publish(topic, data)

        bus.publish = logged

    async def expect(self, label, topic, pred=lambda d: True, since=0):
        """Wait for a message on `topic` matching `pred`, counting ones already seen after `since`."""
        for t, d in self.seen[since:]:
            if t == topic and pred(d):
                return self.ok(label, d)
        fut = asyncio.get_event_loop().create_future()
        w = (topic, pred, fut)
        self.waiters.append(w)
        try:
            d = await asyncio.wait_for(fut, self.timeout)
        except TimeoutError:
            raise SystemExit(self.fail(label, topic)) from None
        finally:
            self.waiters.remove(w)
        return self.ok(label, d)

    def ok(self, label, d):
        print(f"  ok  {time.monotonic() - self.t0:6.2f}s  {label}")
        return d

    def fail(self, label, topic):
        print(f"  FAIL  {label}: no {topic} within {self.timeout}s")
        return 1


async def main(args):
    real = [x for x in args.real.split(",") if x]
    unknown = set(real) - set(LANES)
    if unknown:
        sys.exit(f"--real: unknown lane(s) {sorted(unknown)}; choose from {LANES}")
    try:
        gem = importlib.import_module("coord.gem")
    except ImportError:
        gem = None
    fake_lanes = [lane for lane in LANES if lane not in real]

    def gemini_status():
        s = gem.status() if gem else {"mode": "off", "calls_last_hour": 0, "stand_ins": []}
        s = dict(s, stand_ins=sorted(set(s["stand_ins"]) | {f"fake-{x}" for x in fake_lanes}))
        if not gem:
            s["stand_ins"] = sorted(set(s["stand_ins"]) | {"no-coord.gem"})
        return s

    def live_problems(s):
        out = [] if s["mode"] == "live" else [f"GEMINI_MODE is {s['mode']}, not live"]
        return out + [f"stand-in active: {x}" for x in s["stand_ins"]]

    if args.require_live:
        problems = live_problems(gemini_status())
        if problems:
            print("--require-live failed before start:\n  " + "\n  ".join(problems))
            return 2

    runs = ROOT / "runs"
    runs.mkdir(exist_ok=True)
    bus, bus_kind = make_bus()
    run = Run(bus, runs / f"{args.seed}.jsonl", args.timeout)
    print(f"seed {args.seed} | bus: {bus_kind} | real: {real or 'none'} | fake: {fake_lanes}")
    print(f"log: {run.log.name}")

    world = fakes.FakeWorld(args.seed)
    if not args.auto_approve:
        print("  (no --auto-approve: answer each gate/request here, y/n)")

    async def answer(req):
        if args.auto_approve:
            yes = True
        else:
            line = await asyncio.get_event_loop().run_in_executor(
                None, input, f"  approve {req['kind']}: {req['summary']}? [y/n] ")
            yes = line.strip().lower().startswith("y")
        await bus.publish("gate/answer", {"id": req["id"], "approved": yes, "by": "operator"})

    bus.subscribe("gate/request", lambda req: asyncio.ensure_future(answer(req)))

    # Consumers first, sim last: sim publishes scene/loaded as it starts.
    mods = {}
    for lane in ("voice", "planner", "perception", "sim"):
        if lane in real:
            mod = importlib.import_module(lane)
            mods[lane] = (await call(mod.start, bus), mod)
        elif lane == "planner":
            await fakes.fake_planner(bus, world, step=args.step)
        else:
            await getattr(fakes, f"fake_{lane}")(bus, world)

    async def gemini_beat():
        while True:
            await bus.publish("status/gemini", gemini_status())
            await asyncio.sleep(2)

    beat = asyncio.ensure_future(gemini_beat())

    def is_move(d):
        return d["action"] == "move"

    try:
        await run.expect("scene loaded", "scene/loaded")
        await run.expect("Scout exploring", "scout/goto")
        await run.expect("map published", "map/cells")
        await run.expect("casualty found", "map/casualties", lambda d: len(d) > 0)
        r1 = await run.expect("route proposed", "route/proposed")
        await run.expect("route verified", "route/verified", lambda d: d["id"] == r1["id"] and d["ok"])
        await run.expect("human approved", "gate/answer", lambda d: d["approved"])
        await run.expect("Responder started", "responder/action", is_move)

        mark = len(run.seen)
        if "sim" in real:
            await call(hook(mods["sim"], "trigger_aftershock"))
        else:
            await world.aftershock(bus)
        await run.expect("aftershock fired", "world/change", since=mark)
        r2 = await run.expect("re-planned", "route/proposed", lambda d: d["id"] != r1["id"], mark)
        if r2["cells"] == r1["cells"]:
            raise SystemExit(run.fail("re-plan changed the route", "route/proposed"))
        await run.expect("re-plan verified", "route/verified",
                         lambda d: d["id"] == r2["id"] and d["ok"], mark)
        await run.expect("Responder moving on new route", "responder/action",
                         lambda d: is_move(d) and d["route"] == r2["id"], mark)

        last = r2
        if args.inject:
            cell = pick_inject_cell(r2, args.inject_cell)
            mark = len(run.seen)
            print(f"  ..  injecting a block at {cell} (unscripted change)")
            if "sim" in real:
                await call(hook(mods["sim"], "inject"), cell)
            else:
                await world.inject(cell)
            r3 = await run.expect("re-planned after injection", "route/proposed",
                                  lambda d: d["id"] != r2["id"], mark)
            if [cell[0], cell[1]] in [c[:2] for c in r3["cells"]]:
                raise SystemExit(run.fail("new route avoids the injected block", "route/proposed"))
            run.ok(f"injected block changed the route ({r2['id']} -> {r3['id']})", r3)
            last = r3

        await run.expect("supply delivered", "responder/action",
                         lambda d: d["action"] == "place_supply" and d["route"] == last["id"])
        await run.expect("handover report", "report/handover")
        await bus.publish("status/gemini", gemini_status())
    finally:
        beat.cancel()
        run.log.close()

    if args.require_live:
        problems = live_problems(run.gemini or gemini_status())
        if problems:
            print("--require-live failed:\n  " + "\n  ".join(problems))
            return 2
    print(f"scenario complete: {len(run.seen)} messages")
    return 0


def hook(started, name):
    """`name` on what the lane's start(bus) returned, else on the lane module."""
    for obj in started:
        if callable(getattr(obj, name, None)):
            return getattr(obj, name)
    raise SystemExit(f"real sim has no {name}(); needed for this step (T05, issue #13)")


def pick_inject_cell(route, given):
    if given:
        return [int(v) for v in given.split(",")][:2]
    cells = route["cells"]
    at_wall = [c for c in cells if c[0] == fakes.WALL_X]
    return (at_wall or cells[len(cells) // 2 : len(cells) // 2 + 1])[0][:2]


def parse(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--auto-approve", action="store_true",
                   help="answer every gate/request yes (tests only; the demo uses the console)")
    p.add_argument("--require-live", action="store_true",
                   help="fail (exit 2) if GEMINI_MODE is not live or any stand-in is active")
    p.add_argument("--real", default="", help="comma list of lanes to run for real, e.g. sim,planner")
    p.add_argument("--no-inject", dest="inject", action="store_false",
                   help="skip the injected block (the unscripted change)")
    p.add_argument("--inject-cell", help="x,y grid cell for the injected block (default: on route)")
    p.add_argument("--step", type=float, default=0.3, help="fake Responder drive time, seconds")
    p.add_argument("--timeout", type=float, default=10.0, help="seconds to wait for each milestone")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse())))
