"""B3-SEED-SWEEP: run the B3 scenario over several seeds and measure the safe-success rate.

    python tools/seed_sweep_b3.py                     # seeds 0-4, table into runs/full_test.md
    python tools/seed_sweep_b3.py --seeds 0-9 --timeout 900 --output runs/b3_sweep.md

Each seed runs in its own subprocess (GEMINI_MODE=off, a timeout), so one hung or crashed seed
cannot take the sweep down. What a seed runs depends on what this checkout has:

- "shift" mode, when tools/run_b2.py takes floor= (e2e-b3, #185): the real L1 -> B3 rescue with a
  slab dropped on the Scout's planned route in B3, seeded through LevelWorld(seed=N). Safe success
  means every e2e step passed: descended to B3, stopped short of the slab, mapped it from its own
  measurements, re-planned round it, never entered it, reached c3, no teleport, Responder route.
- "descent" mode otherwise: the unscripted L1 -> B3 descent (sim.demo_descent, floor B3) with
  random/numpy seeded. Safe success means it reached c3 on B3 via L1 > ground > B1 > B2 > B3, with
  no move per tick over MAX_JUMP (no teleport) and a Responder route over the Scout's map. No slab
  shift is tested in this mode, and the table says so.

Every number in the table comes from a run; a seed that did not run is SKIPPED or TIMEOUT, never
counted as a pass. The table goes between the SEED-SWEEP-B3 markers (tools/seed_sweep.py's
write_section: that section is replaced if present, appended otherwise).
"""

import argparse
import inspect
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import seed_sweep as ss

FLOOR = "B3"
PATH = ["L1", "ground", "B1", "B2", "B3"]
MAX_JUMP = 0.035          # metres per 0.1 s tick, as tools/run_b2.py
TAG = "B3SWEEP "          # prefix of the child's one JSON result line


def mode(root=ROOT):
    """'shift' if run_b2.run takes floor= (e2e-b3 merged), else 'descent'."""
    try:
        sys.path.insert(0, str(root))
        from tools import run_b2
    except Exception:  # noqa: BLE001 -- no run_b2 or it fails to import: descent only
        return "descent"
    return "shift" if "floor" in inspect.signature(run_b2.run).parameters else "descent"


def child_shift(seed, max_t):
    from tools import run_b2

    verdict, path = run_b2.run(seed=seed, max_t=max_t, floor=FLOOR)
    failed = list(verdict["failed"])
    return {"mode": "shift", "safe": not failed, "passed": len(verdict["passed"]),
            "steps": len(verdict["steps"]), "failed": failed, "log": str(path)}


def child_descent(seed, max_t):
    import random

    import numpy as np

    random.seed(seed)
    np.random.seed(seed)
    from sim.demo_descent import run

    out = run(max_t=max_t, floor=FLOOR)
    checks = {"reached c3 on B3": bool(out["reached"]),
              "descended L1 > ground > B1 > B2 > B3": out["levels"][:len(PATH)] == PATH,
              "no teleport": out["max_jump"] <= MAX_JUMP,
              "Responder route over the Scout's map": out["responder_route"] == "ok"}
    failed = [k for k, ok in checks.items() if not ok]
    return {"mode": "descent", "safe": not failed, "passed": len(checks) - len(failed),
            "steps": len(checks), "failed": failed, "t": out["t"], "max_jump": out["max_jump"],
            "levels": out["levels"]}


def child(seed, max_t, which):
    result = (child_shift if which == "shift" else child_descent)(seed, max_t)
    print(TAG + json.dumps(result), flush=True)
    return 0 if result["safe"] else 1


def run_seed(seed, timeout, max_t, which, root=ROOT, runner=subprocess.run):
    """One seed in a subprocess: dict with seed, status (pass/fail/timeout/error), seconds, reason."""
    cmd = [sys.executable, str(pathlib.Path(__file__).resolve()), "--child", which,
           "--seed", str(seed), "--max-t", str(max_t)]
    env = dict(os.environ, GEMINI_MODE="off", PYTHONPATH=str(root))
    start = time.monotonic()
    try:
        proc = runner(cmd, check=False, cwd=root, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"seed": seed, "status": "timeout", "seconds": round(time.monotonic() - start, 1),
                "reason": f"no result after {timeout:g} s"}
    seconds = round(time.monotonic() - start, 1)
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.startswith(TAG)]
    if not lines:
        tail = ss._reason((proc.stdout or "") + "\n" + (proc.stderr or ""))
        return {"seed": seed, "status": "error", "seconds": seconds, "reason": f"no result: {tail}"}
    res = json.loads(lines[-1][len(TAG):])
    reason = f"{res['passed']}/{res['steps']} checks"
    if res["failed"]:
        reason += "; failed: " + ", ".join(res["failed"])
    if "t" in res:
        reason += f"; sim {res['t']} s, max move {res['max_jump']} m/tick"
    return {"seed": seed, "status": "pass" if res["safe"] and proc.returncode == 0 else "fail",
            "seconds": seconds, "reason": reason.replace("|", "/")}


def sweep(seeds, timeout=900, max_t=600.0, which=None, root=ROOT, runner=subprocess.run):
    """Run every seed; return (results, safe-success rate or None when nothing ran, mode)."""
    which = which or mode(root)
    results = [run_seed(s, timeout, max_t, which, root, runner) for s in seeds]
    ran = [r for r in results if r["status"] in ("pass", "fail")]
    rate = sum(r["status"] == "pass" for r in ran) / len(ran) if ran else None
    return results, rate, which


def section(results, rate, which):
    passed = sum(r["status"] == "pass" for r in results)
    ran = sum(r["status"] in ("pass", "fail") for r in results)
    what = ("e2e-b3: L1 -> B3 with a slab shift on the route in B3, tools/run_b2.py --floor B3"
            if which == "shift" else
            "L1 -> B3 descent, sim.demo_descent (no slab shift on this checkout: e2e-b3 not merged)")
    line = (f"Safe success: {passed}/{ran} = {rate:.0%} (GEMINI_MODE=off, measured)." if rate is not None
            else f"Safe success: n/a, none of {len(results)} seeds gave a result.")
    begin, end = ss.markers(FLOOR)
    rows = [begin, f"## Seed sweep B3 ({what})", "", line, "",
            "| Seed | Result | Seconds | Checks |", "|---|---|---|---|"]
    rows += [f"| {r['seed']} | {r['status'].upper()} | {r['seconds']} | {r['reason']} |" for r in results]
    return "\n".join([*rows, end]) + "\n"


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", default="0-4", help="comma list or a-b range")
    ap.add_argument("--timeout", type=float, default=900, help="wall seconds per seed")
    ap.add_argument("--max-t", type=float, default=600.0, help="sim seconds per seed")
    ap.add_argument("--mode", choices=("shift", "descent"), help="default: shift if this checkout has it")
    ap.add_argument("--output", default="runs/full_test.md")
    ap.add_argument("--child", choices=("shift", "descent"), help=argparse.SUPPRESS)
    ap.add_argument("--seed", type=int, default=0, help=argparse.SUPPRESS)
    return ap.parse_args(argv)


def main(argv=None, root=ROOT, runner=subprocess.run):
    args = parse(argv)
    if args.child:
        return child(args.seed, args.max_t, args.child)
    results, rate, which = sweep(ss.seeds_from(args.seeds), args.timeout, args.max_t, args.mode, root, runner)
    for r in results:
        print(f"seed {r['seed']}: {r['status'].upper()} {r['reason']}", flush=True)
    out = pathlib.Path(args.output)
    out = out if out.is_absolute() else root / out
    ss.write_section(out, section(results, rate, which), FLOOR)
    print(f"mode {which}; safe success {'n/a' if rate is None else f'{rate:.0%}'}; wrote {out}")
    return 0 if results and all(r["status"] == "pass" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
