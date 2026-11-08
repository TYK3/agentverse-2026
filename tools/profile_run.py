"""Sim real-time factor per lane: python tools/profile_run.py.

Measured from outside, no lane code changed. For each lane set (sim alone, then adding
perception, planner and voice) a fresh subprocess starts those lanes on coord.hub.Bus
exactly as tools/demo60.py does (GEMINI_MODE=off, a gate answered yes), lets them warm up,
then samples the sim clock (world.t) against the wall clock for --duration seconds.
RTF = sim seconds / wall seconds; below 1 the sim fell behind real time (demo60 saw 0.77x).

The child also wraps Bus.subscribe to time every subscriber call and books it to the
lane whose module registered it (inclusive: a handler's own nested publishes count too).
Results go to runs/perf.md (overwritten).
"""

import argparse
import asyncio
import importlib
import inspect
import json
import os
import pathlib
import subprocess
import sys
import time
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
ORDER = ("voice", "planner", "perception", "sim")    # consumers first, as demo60 starts them
SETS = {"sim": ["sim"], "+perception": ["sim", "perception"],
        "+planner": ["sim", "perception", "planner"],
        "+voice (all)": ["sim", "perception", "planner", "voice"]}
MARK = "PROFILE_JSON "


# ---- child: one lane set ----------------------------------------------------------------

def lane_of(fn):
    mod = getattr(fn, "__module__", None) or getattr(getattr(fn, "__func__", None), "__module__", "")
    return (mod or "?").split(".")[0]


def handler_name(fn):
    """module.qualname of a subscriber, e.g. perception.grid.Mapper.on_scout."""
    target = getattr(fn, "__func__", fn)
    mod = getattr(target, "__module__", None) or "?"
    return f"{mod}.{getattr(target, '__qualname__', type(fn).__name__)}"


def timed(fn, book, clock=time.perf_counter, detail=None, topic=""):
    """Wrap a subscriber so its wall time (awaited too) is added to book[lane], and, when a
    detail book is given, to detail[(handler, topic)] (each call's ms kept for max)."""
    lane = lane_of(fn)
    key = (handler_name(fn), topic)

    def add(ms):
        book[lane]["ms"] += ms
        if detail is not None:
            d = detail[key]
            d["calls"] += 1
            d["ms"] += ms
            d["max_ms"] = max(d["max_ms"], ms)

    async def finish(start, result):
        try:
            return await result
        finally:
            add((clock() - start) * 1000)

    def wrapper(data):
        start = clock()
        book[lane]["calls"] += 1
        result = fn(data)
        if inspect.isawaitable(result):
            return finish(start, result)
        add((clock() - start) * 1000)
        return result
    return wrapper


def rtf(samples):
    """samples [(wall, sim)] -> sim seconds per wall second over the span, or None."""
    if len(samples) < 2 or samples[-1][0] <= samples[0][0]:
        return None
    return (samples[-1][1] - samples[0][1]) / (samples[-1][0] - samples[0][0])


async def profile(lanes, duration, warmup):
    sys.path.insert(0, str(ROOT))
    from coord.hub import Bus

    bus, book = Bus(), defaultdict(lambda: {"calls": 0, "ms": 0.0})
    subscribe = bus.subscribe
    detail = defaultdict(lambda: {"calls": 0, "ms": 0.0, "max_ms": 0.0})
    bus.subscribe = lambda topic, fn: subscribe(topic, timed(fn, book, detail=detail, topic=topic))

    async def answer(req):
        await bus.publish("gate/answer", {"id": req["id"], "approved": True, "by": "operator"})

    subscribe("gate/request", lambda req: asyncio.ensure_future(answer(req)))
    started = {}
    for lane in [x for x in ORDER if x in lanes]:
        res = importlib.import_module(lane).start(bus)
        started[lane] = await res if inspect.isawaitable(res) else res
    world = started["sim"]
    await asyncio.sleep(warmup)
    book.clear()
    detail.clear()
    samples, end = [], time.monotonic() + duration
    while time.monotonic() < end:
        samples.append((time.monotonic(), float(world.t)))
        await asyncio.sleep(0.1)
    samples.append((time.monotonic(), float(world.t)))
    task = getattr(world, "task", None)
    if task:
        task.cancel()
    wall = samples[-1][0] - samples[0][0]
    return {"lanes": lanes, "rtf": rtf(samples), "wall_s": round(wall, 2),
            "sim_s": round(samples[-1][1] - samples[0][1], 2),
            "handlers": {k: {"calls": v["calls"], "ms": round(v["ms"], 1),
                             "share": round(v["ms"] / 1000 / wall, 3) if wall else None}
                         for k, v in sorted(book.items())},
            "per_handler": [{"handler": h, "topic": t, "calls": v["calls"], "ms": round(v["ms"], 1),
                             "mean_ms": round(v["ms"] / v["calls"], 3) if v["calls"] else 0.0,
                             "max_ms": round(v["max_ms"], 2),
                             "share": round(v["ms"] / 1000 / wall, 4) if wall else None}
                            for (h, t), v in sorted(detail.items(), key=lambda kv: -kv[1]["ms"])]}


# ---- parent ----------------------------------------------------------------------------

def run_set(name, lanes, duration, warmup, timeout, runner=subprocess.run):
    cmd = [sys.executable, str(pathlib.Path(__file__).resolve()), "--child", ",".join(lanes),
           "--duration", str(duration), "--warmup", str(warmup)]
    env = dict(os.environ, GEMINI_MODE="off", PYTHONPATH=str(ROOT))
    try:
        proc = runner(cmd, check=False, cwd=ROOT, env=env, capture_output=True, text=True,
                      timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"set": name, "lanes": lanes, "status": "timeout", "rtf": None, "handlers": {},
                "reason": f"no result after {timeout:g} s"}
    line = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.startswith(MARK)), None)
    if proc.returncode != 0 or line is None:
        tail = (proc.stderr or proc.stdout or "(no output)").strip().splitlines()[-1:]
        return {"set": name, "lanes": lanes, "status": "fail", "rtf": None, "handlers": {},
                "reason": (tail[0] if tail else "")[:150]}
    return {"set": name, "status": "ok", "reason": "", **json.loads(line[len(MARK):])}


def report(rows, duration):
    out = ["# Sim real-time factor per lane", "",
           (f"`python tools/profile_run.py --duration {duration:g}`, GEMINI_MODE=off, measured from "
           "outside (world.t against the wall clock). RTF below 1: the sim fell behind real time."), "",
           "| Lanes running | RTF (sim s / wall s) | Sim s | Wall s | Status |", "|---|---|---|---|---|"]
    for r in rows:
        val = f"{r['rtf']:.2f}x" if r.get("rtf") is not None else "-"
        out.append(f"| {r['set']} ({', '.join(r['lanes'])}) | {val} | {r.get('sim_s', '-')} | "
                   f"{r.get('wall_s', '-')} | {r['status']}{': ' + r['reason'] if r['reason'] else ''} |")
    out += ["", "Bus subscriber time per lane (inclusive), share = handler seconds per wall second:", "",
            "| Lanes running | Lane | Calls | ms | Share |", "|---|---|---|---|---|"]
    for r in rows:
        for lane, h in r.get("handlers", {}).items():
            out.append(f"| {r['set']} | {lane} | {h['calls']} | {h['ms']} | {h['share']} |")
    out += per_handler_table(rows)
    return "\n".join(out) + "\n"


def per_handler_table(rows, lane="perception"):
    """Per-handler cost from the run with the most lanes: `lane` handlers first, then the rest."""
    full = next((r for r in reversed(rows) if r.get("per_handler")), None)
    if full is None:
        return []
    mine = [h for h in full["per_handler"] if h["handler"].split(".")[0] == lane]
    rest = [h for h in full["per_handler"] if h["handler"].split(".")[0] != lane]
    total = sum(h["ms"] for h in mine)
    out = ["", f"## Per-handler cost ({full['set']}: {', '.join(full['lanes'])})", "",
           (f"{lane} handlers total {total:.1f} ms over {full.get('wall_s', '-')} s wall. Inclusive "
           "time (nested publishes count), share = handler seconds per wall second."), "",
           "| Handler | Topic | Calls | Total ms | Mean ms | Max ms | Share |",
           "|---|---|---|---|---|---|---|"]
    out += [f"| {h['handler']} | {h['topic']} | {h['calls']} | {h['ms']} | {h['mean_ms']} | "
            f"{h['max_ms']} | {h['share']} |" for h in mine + rest]
    return out


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--duration", type=float, default=20.0, help="measured wall seconds per set")
    ap.add_argument("--warmup", type=float, default=3.0, help="seconds after start before measuring")
    ap.add_argument("--timeout", type=float, default=180.0, help="seconds per set")
    ap.add_argument("--output", default="runs/perf.md")
    ap.add_argument("--child", help=argparse.SUPPRESS)
    return ap.parse_args(argv)


def main(argv=None, runner=subprocess.run):
    args = parse(argv)
    if args.child:
        result = asyncio.run(profile(args.child.split(","), args.duration, args.warmup))
        print(MARK + json.dumps(result), flush=True)
        os._exit(0)          # lanes may leave threads or tasks behind; the result is out
    rows = []
    for name, lanes in SETS.items():
        rows.append(run_set(name, lanes, args.duration, args.warmup, args.timeout, runner))
        r = rows[-1]
        print(f"{name:14} {r['status']:7} rtf={r.get('rtf')}", flush=True)
    out = pathlib.Path(args.output)
    out = out if out.is_absolute() else ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report(rows, args.duration))
    print(f"wrote {out}")
    return 0 if all(r["status"] == "ok" for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
