"""demo60: a fixed-seed, 60-second real run with a reproducible pass/fail summary (ref #31).

    GEMINI_MODE=off python tools/demo60.py --seed 7 --auto-approve              # one run
    GEMINI_MODE=off python tools/demo60.py --seed 7 --auto-approve --repeat 3   # same seed 3 times

Every lane is real (sim, perception, planner, voice started with start(bus) on coord.hub.Bus, as the
hub does). Python's, numpy's and the sim world's random generators are seeded. The run lasts exactly
DURATION seconds of wall time (the sim ticks in real time). The runner does three things only:
answers gate/request (with --auto-approve; this is a test run, not the console), drops the sim's spare
block on the Responder's route once it first moves (ahead of it, in the Scout's line of sight when
such a cell exists: the one unscripted change), and logs every bus message.

The verdict comes from evaluate() over the log alone, so the same log always gives the same summary.
--repeat N runs N fresh processes with the same seed and reports whether the steps that passed
were the same every time. This is a reproducibility check of the real stack, not a pitch video. The
summary also gives sim seconds per wall second: below 1 the sim fell behind real time, so any lane
timing itself on the wall clock sees a different world at the same wall time.

runs/demo60-<seed>[-<n>].jsonl: every bus message {"t","topic","data"} except raw sensors/scout and
responder/pose frames (sampled every POSE_EVERY s as _probe/pose), plus _runner/action records and
the final _runner/summary. Exit 0 only if every step passed (and, with --repeat, all runs agreed).
"""

import argparse
import asyncio
import importlib
import json
import math
import os
import pathlib
import random
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DURATION = 60.0
LANES = ("voice", "planner", "perception", "sim")   # consumers first: sim publishes scene/loaded on start
RES = 0.05
SHIFT_AHEAD = 0.5       # metres ahead of the Responder along its route
SHIFT_LATEST = 50.0     # no shift after this: too little time left to see a recheck
POSE_EVERY = 0.5
STILL = 0.01            # metres

# (name, what must be in the log). Order matters only for the printout; each check is independent.
STEPS = (
    "scene loaded",
    "casualty found",
    "route verified",
    "move permit granted",
    "Responder moving",
    "shift dropped on the route",
    "permit revoked after the shift",
    "Responder off the revoked route",
    "permit granted again after the shift",
    "Responder moving again",
)


# ---- the verdict (pure: the same events always give the same summary) ---------------------------
def evaluate(events, duration=DURATION):
    """Summary of one run from its log events: [(t, topic, data), ...] in time order.

    Returns {"steps": {name: {"ok": bool, "t": float | None, "detail": str}}, "passed": [...],
    "failed": [...]}. A step's t is when it first held.
    """
    out = {}

    def hit(name, t, detail):
        out.setdefault(name, {"ok": True, "t": round(t, 2), "detail": detail})

    first = {}
    for t, topic, data in events:
        first.setdefault(topic, (t, data))
    if "scene/loaded" in first:
        t, d = first["scene/loaded"]
        hit("scene loaded", t, f"scene {d['scene']}")
    for t, topic, d in events:
        if topic == "map/casualties" and d:
            hit("casualty found", t, f"{d[0]['id']} conf {d[0]['confidence']}")
            break
    verified = {}
    for t, topic, d in events:
        if topic == "route/verified" and d["ok"]:
            verified.setdefault(d["id"], t)
            hit("route verified", t, d["id"])
    granted = [(t, d) for t, topic, d in events if topic == "permit/route" and d["granted"]]
    if granted:
        hit("move permit granted", granted[0][0], granted[0][1]["route"])
    poses = [(t, d) for t, topic, d in events if topic == "_probe/pose" and d.get("responder")]
    moving = [(t, d) for t, d in poses if d.get("responder_state") == "moving"]
    if moving:
        hit("Responder moving", moving[0][0], f"on {moving[0][1].get('responder_route')}")
    shift = next(((t, d) for t, topic, d in events if topic == "_runner/action" and d.get("action") == "inject"),
                 None)
    if shift:
        ts, sd = shift
        hit("shift dropped on the route", ts, f"{sd['block']} on {sd['route']} at {sd['cell'][:2]}"
            + ("" if sd.get("in_scout_view") else " (not in the Scout's view)"))
        revoked = next(((t, d) for t, topic, d in events
                        if topic == "permit/route" and t >= ts and not d["granted"]), None)
        if revoked:
            tr, rd = revoked
            hit("permit revoked after the shift", tr, f"{rd['route']}: {rd['reason'][:80]}")
            off = next(((t, d) for t, d in poses if t >= tr
                        and not (d.get("responder_state") == "moving" and d.get("responder_route") == rd["route"])),
                       None)
            if off:
                hit("Responder off the revoked route", off[0], f"{off[1].get('responder_state')} on "
                    f"{off[1].get('responder_route')}")
            again = next(((t, d) for t, topic, d in events if topic == "permit/route" and t >= tr and d["granted"]),
                         None)
            if again:
                ta, ad = again
                hit("permit granted again after the shift", ta, f"{ad['route']}: {ad['reason'][:60]}")
                resumed = next(((t, d) for t, d in poses if t >= ta and d.get("responder_state") == "moving"),
                               None)
                if resumed:
                    hit("Responder moving again", resumed[0], f"on {resumed[1].get('responder_route')}")
    steps = {name: out.get(name, {"ok": False, "t": None, "detail": f"not seen within {duration:.0f} s"})
             for name in STEPS}
    clock = [(t, d["sim_t"]) for t, d in poses if "sim_t" in d] or             [(t, d["sim_t"]) for t, topic, d in events if topic == "_probe/pose" and "sim_t" in d]
    sim_rate = None
    if len(clock) >= 2 and clock[-1][0] > clock[0][0]:
        sim_rate = round((clock[-1][1] - clock[0][1]) / (clock[-1][0] - clock[0][0]), 3)
    return {"steps": steps, "passed": [n for n in STEPS if steps[n]["ok"]],
            "failed": [n for n in STEPS if not steps[n]["ok"]],
            "sim_seconds_per_wall_second": sim_rate}


def agree(summaries):
    """True if every summary passed exactly the same steps."""
    return len({tuple(s["passed"]) for s in summaries}) <= 1


def shift_cell(cells, responder_xy, ahead=SHIFT_AHEAD, visible=None):
    """(cell, in_view): the first route cell >= `ahead` m past the cell nearest the Responder, preferring
    one visible(cell) accepts, never one of the last 3 cells (the goal). (None, False) if none."""
    centre = [((c[0] + 0.5) * RES, (c[1] + 0.5) * RES) for c in cells]
    if not cells:
        return None, False
    near = min(range(len(cells)), key=lambda n: math.dist(centre[n], responder_xy))
    run, first = 0.0, None
    for n in range(near + 1, len(cells) - 3):
        run += math.dist(centre[n - 1], centre[n])
        if run < ahead:
            continue
        first = first or cells[n]
        if visible is None or visible(cells[n]):
            return cells[n], visible is not None
    return first, False


# ---- one real run ------------------------------------------------------------------------------
def in_scout_view(world, cell, max_range=4.0):
    import numpy as np

    from sim import sensors

    origin = np.asarray(world.pos, float)
    target = np.array([(cell[0] + 0.5) * RES, (cell[1] + 0.5) * RES, origin[2]])
    dist = float(np.linalg.norm(target - origin))
    if dist > max_range or dist < 1e-6:
        return False
    hit, _ = sensors._ray(world.m, world.d, origin, (target - origin) / dist, world.scout, sensors.SENSE_GROUPS)
    return hit < 0 or hit >= dist - RES


async def run_once(seed, f, auto_approve, duration=DURATION):
    """One run, logged to the open text file f (closed here)."""
    import numpy as np

    from coord.hub import Bus
    from coord.messages import validate_payload

    random.seed(seed)
    np.random.seed(seed)
    bus = Bus()
    t0 = time.monotonic()
    events = []
    latest = {}

    def now():
        return round(time.monotonic() - t0, 2)

    def write(topic, data, **extra):
        if not f.closed:
            f.write(json.dumps({"t": now(), "topic": topic, "data": data, **extra}, allow_nan=False) + "\n")

    publish = bus.publish

    async def logged(topic, data):
        try:
            validate_payload(topic, data)
        except ValueError as e:
            write(topic, data, rejected=str(e).splitlines()[0])
            raise
        latest[topic] = data
        if topic not in ("sensors/scout", "responder/pose"):
            write(topic, data)
            events.append((now(), topic, data))
        await publish(topic, data)

    bus.publish = logged

    def note(topic, data):
        write(topic, data)
        events.append((now(), topic, data))

    async def answer(req):
        if not auto_approve:
            return                  # no console in a demo60 run: an unanswered gate stays unanswered
        await bus.publish("gate/answer", {"id": req["id"], "approved": True, "by": "operator"})
        note("_runner/action", {"action": "gate/answer", "id": req["id"], "approved": True})

    def on_request(req):
        asyncio.ensure_future(answer(req))

    bus.subscribe("gate/request", on_request)
    started = {}
    for lane in LANES:
        res = importlib.import_module(lane).start(bus)
        started[lane] = await res if asyncio.iscoroutine(res) else res
    world = started["sim"]
    world.rng = np.random.default_rng(seed)       # the sim's acoustic noise, seeded
    responder = getattr(world, "responder", None)

    shifted = False
    next_pose = 0.0
    while now() < duration:
        if now() >= next_pose:
            pose = {"sim_t": round(float(world.t), 2), "scout": [round(float(v), 3) for v in world.pos],
                    "scout_state": world.state}
            if responder is not None:
                pose.update(responder=[round(float(v), 3) for v in responder.pos],
                            responder_state=responder.state, responder_route=responder.route)
            note("_probe/pose", pose)
            next_pose += POSE_EVERY
        if (not shifted and responder is not None and responder.state == "moving" and now() <= SHIFT_LATEST):
            route = next((d for t, tp, d in reversed(events)
                          if tp == "route/proposed" and d["id"] == responder.route), None)
            if route:
                cell, seen = shift_cell(route["cells"], responder.pos[:2],
                                        visible=lambda c: in_scout_view(world, c))
                if cell is not None:
                    name = world.inject(cell)
                    note("_runner/action", {"action": "inject", "cell": cell, "block": name, "route": route["id"],
                                            "in_scout_view": seen,
                                            "responder": [round(float(v), 3) for v in responder.pos]})
                    shifted = True
        await asyncio.sleep(0.05)
    task = getattr(world, "task", None)
    if task:
        task.cancel()
    summary = evaluate(events, duration)
    summary.update(seed=seed, duration=duration, gemini_mode=os.environ.get("GEMINI_MODE", "off"))
    write("_runner/summary", summary)
    f.close()
    return summary


def show(summary, label=""):
    rate = summary.get("sim_seconds_per_wall_second")
    print(f"demo60 seed {summary['seed']}{label}: {len(summary['passed'])}/{len(STEPS)} steps passed"
          + (f" (sim ran at {rate:.2f}x wall time)" if rate else ""))
    for name in STEPS:
        s = summary["steps"][name]
        t = f"{s['t']:6.1f}s" if s["t"] is not None else "     - "
        print(f"  {'ok  ' if s['ok'] else 'FAIL'} {t}  {name}: {s['detail']}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--auto-approve", action="store_true", help="answer every gate/request yes (test run)")
    p.add_argument("--repeat", type=int, default=1, help="run N fresh processes with the same seed")
    p.add_argument("--duration", type=float, default=DURATION, help=argparse.SUPPRESS)
    p.add_argument("--summary-out", help=argparse.SUPPRESS)     # used by --repeat for each child run
    args = p.parse_args(argv)
    os.environ.setdefault("GEMINI_MODE", "off")
    runs = ROOT / "runs"
    runs.mkdir(exist_ok=True)

    if args.repeat <= 1:
        name = f"demo60-{args.seed}" + (f"-{pathlib.Path(args.summary_out).stem.split('-')[-1]}"
                                        if args.summary_out else "")
        log = open(runs / f"{name}.jsonl", "w", encoding="utf-8")  # noqa: SIM115 (run_once closes it)
        summary = asyncio.run(run_once(args.seed, log, args.auto_approve, args.duration))
        if args.summary_out:
            pathlib.Path(args.summary_out).write_text(json.dumps(summary), encoding="utf-8")
        else:
            show(summary)
            print(f"log: {runs / (name + '.jsonl')}")
        return 0 if not summary["failed"] else 1

    summaries = []
    for n in range(1, args.repeat + 1):
        out = runs / f"demo60-{args.seed}-summary-{n}.json"
        cmd = [sys.executable, str(pathlib.Path(__file__).resolve()), "--seed", str(args.seed),
               "--duration", str(args.duration), "--summary-out", str(out)]
        if args.auto_approve:
            cmd.append("--auto-approve")
        subprocess.run(cmd, cwd=ROOT, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not out.exists():
            print(f"run {n}: no summary (the run crashed); see runs/demo60-{args.seed}-{n}.jsonl")
            return 1
        summaries.append(json.loads(out.read_text(encoding="utf-8")))
        show(summaries[-1], f" run {n}/{args.repeat}")
    same = agree(summaries)
    print(f"reproducible: {'yes' if same else 'NO'} (passed steps "
          f"{'identical' if same else 'differ'} across {args.repeat} runs)")
    return 0 if same and not any(s["failed"] for s in summaries) else 1


if __name__ == "__main__":
    sys.exit(main())
