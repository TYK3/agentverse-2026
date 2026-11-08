"""Rescue rate per injected fault: python tools/fault_sweep.py.

Runs tools/run_rescue.py once per (fault, seed), each in its own subprocess with
GEMINI_MODE=off and a timeout, and writes a rescue-rate-per-fault table into
runs/full_test.md between the FAULT-SWEEP markers (replaced if present, else appended).

Faults (all injected by this tool, no lane code changed):
  baseline         nothing injected
  dropout          drop DROPOUT of sensors/scout frames (seeded)
  noise            Gaussian noise, NOISE_M metres sigma, on LiDAR ranges and depth points
  late_shift       the slab shift comes later: run_rescue --drive-before LATE_DRIVE
  casualty_offset  map/casualties positions moved by CASUALTY_OFFSET (localisation error)

dropout, noise and casualty_offset wrap coord.hub.Bus.publish in the child process before
run_rescue starts, so every lane receives the faulty message (run_rescue's own log records
the message before the fault is applied). If tools/run_rescue.py is missing (it lands
with #52), every row is SKIPPED with the reason, never passed.
"""

import argparse
import asyncio
import importlib.util
import os
import pathlib
import random
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
RESCUE = "tools/run_rescue.py"
BEGIN = "<!-- FAULT-SWEEP:BEGIN -->"
END = "<!-- FAULT-SWEEP:END -->"
DROPOUT = 0.3
NOISE_M = 0.05
LATE_DRIVE = 1.0
CASUALTY_OFFSET = (0.3, 0.0, 0.0)
FAULTS = ("baseline", "dropout", "noise", "late_shift", "casualty_offset")


# ---- fault injection (child side) -------------------------------------------------------

def fault_filter(fault, rng):
    """Return f(topic, data) -> data or None (drop) for one fault; pure, testable."""
    def apply(topic, data):
        if fault == "dropout" and topic == "sensors/scout":
            return None if rng.random() < DROPOUT else data
        if fault == "noise" and topic == "sensors/scout" and isinstance(data, dict):
            out = dict(data)
            if isinstance(out.get("lidar"), list):
                out["lidar"] = [max(0.0, r + rng.gauss(0, NOISE_M)) for r in out["lidar"]]
            if isinstance(out.get("points"), list):
                out["points"] = [[c + rng.gauss(0, NOISE_M) for c in p] for p in out["points"]]
            return out
        if fault == "casualty_offset" and topic == "map/casualties" and isinstance(data, list):
            return [dict(c, pos=[p + o for p, o in zip(c["pos"], CASUALTY_OFFSET, strict=False)])
                    if isinstance(c, dict) and "pos" in c else c for c in data]
        return data
    return apply


def install(fault, seed):
    """Wrap coord.hub.Bus.publish so every subscriber gets the faulty message."""
    from coord.hub import Bus

    apply, publish = fault_filter(fault, random.Random(seed)), Bus.publish

    async def faulty(self, topic, data):
        data = apply(topic, data)
        if data is not None:
            await publish(self, topic, data)

    Bus.publish = faulty


def child(fault, seed, rescue_args, root=ROOT):
    sys.path.insert(0, str(root))
    install(fault, seed)
    spec = importlib.util.spec_from_file_location("run_rescue", root / RESCUE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return asyncio.run(mod.main(mod.parse(rescue_args)))


# ---- sweep (parent side) ----------------------------------------------------------------

def command(fault, seed):
    args = ["--auto-approve", "--seed", str(seed)]
    if fault == "late_shift":
        args += ["--drive-before", str(LATE_DRIVE)]
    return [sys.executable, str(pathlib.Path(__file__).resolve()), "--child", fault,
            "--fault-seed", str(seed), "--", *args]


def _text(data):
    if data is None:
        return ""
    return data.decode(errors="replace") if isinstance(data, bytes) else data


def _reason(output, limit=120):
    lines = [ln.strip() for ln in output.strip().splitlines() if ln.strip()]
    return (lines[-1] if lines else "(no output)").replace("|", "/")[:limit]


def run_one(fault, seed, timeout, root=ROOT, runner=subprocess.run):
    if not (root / RESCUE).exists():
        return {"fault": fault, "seed": seed, "status": "skipped", "seconds": 0.0,
                "reason": f"{RESCUE} not on this checkout"}
    env = dict(os.environ, GEMINI_MODE="off", PYTHONPATH=str(root))
    start = time.monotonic()
    try:
        proc = runner(command(fault, seed), check=False, cwd=root, env=env,
                      capture_output=True, text=True, timeout=timeout)
        status = "pass" if proc.returncode == 0 else "fail"
        out = _text(proc.stdout)
        reason = _reason(out if out.strip() else _text(proc.stderr))
    except subprocess.TimeoutExpired as exc:
        status, reason = "timeout", f"no result after {timeout:g} s: " + _reason(_text(exc.stdout))
    return {"fault": fault, "seed": seed, "status": status,
            "seconds": round(time.monotonic() - start, 1), "reason": reason}


def sweep(faults, seeds, timeout=600, root=ROOT, runner=subprocess.run):
    """Return (rows, rates) with rates[fault] = pass fraction of runs, or None if all skipped."""
    rows = [run_one(f, s, timeout, root, runner) for f in faults for s in seeds]
    rates = {}
    for f in faults:
        ran = [r for r in rows if r["fault"] == f and r["status"] != "skipped"]
        rates[f] = sum(r["status"] == "pass" for r in ran) / len(ran) if ran else None
    return rows, rates


def section(rows, rates):
    out = [BEGIN, "## Fault sweep (e2e rescue under injected faults)", "",
           (f"GEMINI_MODE=off, --auto-approve. Faults: dropout {DROPOUT:.0%} of Scout frames, "
           f"noise {NOISE_M} m sigma, late shift --drive-before {LATE_DRIVE}, "
           f"casualty offset {list(CASUALTY_OFFSET)} m."), "",
           "| Fault | Rescue rate | Runs |", "|---|---|---|"]
    for f, rate in rates.items():
        mine = [r for r in rows if r["fault"] == f]
        ran = [r for r in mine if r["status"] != "skipped"]
        passed = sum(r["status"] == "pass" for r in ran)
        out.append(f"| {f} | {f'{passed}/{len(ran)} = {rate:.0%}' if rate is not None else 'n/a (skipped)'}"
                   f" | {len(mine)} |")
    out += ["", "| Fault | Seed | Result | Seconds | Reason / tail |", "|---|---|---|---|---|"]
    out += [f"| {r['fault']} | {r['seed']} | {r['status'].upper()} | {r['seconds']} | {r['reason']} |"
            for r in rows]
    return "\n".join([*out, END]) + "\n"


def write_section(path, text):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text() if path.exists() else ""
    if BEGIN in old and END in old:
        head, rest = old.split(BEGIN, 1)
        new = head + text + rest.split(END, 1)[1].lstrip("\n")
    else:
        new = old + ("\n" if old and not old.endswith("\n") else "") + ("\n" if old else "") + text
    path.write_text(new)


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--faults", default=",".join(FAULTS), help="comma list from: " + ", ".join(FAULTS))
    ap.add_argument("--seeds", default="1", help="comma list of seeds per fault")
    ap.add_argument("--timeout", type=float, default=600, help="seconds per run")
    ap.add_argument("--output", default="runs/full_test.md")
    ap.add_argument("--child", choices=FAULTS, help=argparse.SUPPRESS)
    ap.add_argument("--fault-seed", type=int, default=1, help=argparse.SUPPRESS)
    ap.add_argument("rescue_args", nargs="*", help=argparse.SUPPRESS)
    return ap.parse_args(argv)


def main(argv=None, root=ROOT, runner=subprocess.run):
    args = parse(argv)
    if args.child:
        return child(args.child, args.fault_seed, args.rescue_args, root)
    faults = [f.strip() for f in args.faults.split(",") if f.strip()]
    unknown = set(faults) - set(FAULTS)
    if unknown:
        raise SystemExit(f"unknown fault(s): {sorted(unknown)}")
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    rows, rates = sweep(faults, seeds, args.timeout, root, runner)
    for r in rows:
        print(f"{r['fault']:16} seed {r['seed']}: {r['status'].upper()} {r['reason']}", flush=True)
    out = pathlib.Path(args.output)
    out = out if out.is_absolute() else root / out
    write_section(out, section(rows, rates))
    print(f"wrote {out}")
    return 0 if all(r["status"] in ("pass", "skipped") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
