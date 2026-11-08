"""E2E rescue over several seeds with a success-rate table: python tools/seed_sweep.py.

Each seed runs `tools/run_rescue.py --auto-approve --seed N` in its own subprocess with
GEMINI_MODE=off and a timeout. Assumed interface (from #52's branch): exit 0 when every
step passed, 1 otherwise; the last stdout line reads "K/M steps passed[; failed: ...]";
the bus log goes to runs/rescue-<seed>.jsonl. If the script is missing, every seed is
SKIPPED with the reason, never passed.

`--floor B2` (or B1) sweeps the unscripted L1 -> B2 descent (sim.demo_descent) instead,
random/numpy seeded per seed; a seed passes only if the Scout reached that floor. Its table
goes in its own SEED-SWEEP-B2 section.

The table goes into runs/full_test.md between the SEED-SWEEP markers (that section is
replaced if present, appended otherwise). full_test.py can call `sweep()` and
`write_section()` directly.
"""

import argparse
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
RESCUE = "tools/run_rescue.py"
BEGIN = "<!-- SEED-SWEEP:BEGIN -->"
END = "<!-- SEED-SWEEP:END -->"
DESCENT_FLOORS = ("B1", "B2")


def markers(floor=None):
    """Section markers: the rescue sweep, or one per descent floor (SEED-SWEEP-B2)."""
    if floor is None:
        return BEGIN, END
    return f"<!-- SEED-SWEEP-{floor}:BEGIN -->", f"<!-- SEED-SWEEP-{floor}:END -->"


def descent_child(floor, seed):
    """Run sim.demo_descent to `floor` with random/numpy seeded; exit 0 only if it got there."""
    import random

    import numpy as np

    sys.path.insert(0, str(ROOT))
    random.seed(seed)
    np.random.seed(seed)
    from sim.demo_descent import run

    out = run(floor=floor)
    ok = bool(out["reached"]) and out["levels"][-1:] == [floor]
    print(f"reached={out['reached']} t={out['t']} levels={'>'.join(out['levels'])} "
          f"max_jump={out['max_jump']} responder_route={out['responder_route']}")
    return 0 if ok else 1


def command(seed, floor=None):
    if floor is None:
        return [sys.executable, RESCUE, "--auto-approve", "--seed", str(seed)]
    return [sys.executable, str(pathlib.Path(__file__).resolve()), "--descent-child", floor,
            "--seed", str(seed)]


def _text(data):
    if data is None:
        return ""
    return data.decode(errors="replace") if isinstance(data, bytes) else data


def _reason(output, limit=120):
    lines = [ln.strip() for ln in output.strip().splitlines() if ln.strip()]
    text = lines[-1] if lines else "(no output)"
    return text.replace("|", "/")[:limit]


def run_seed(seed, timeout, root=ROOT, runner=subprocess.run, floor=None):
    """One seed: dict with seed, status (pass/fail/timeout/skipped), seconds, reason.
    floor=None runs the e2e rescue; floor="B2" runs the L1 -> B2 descent instead."""
    need = RESCUE if floor is None else "sim/demo_descent.py"
    if not (root / need).exists():
        return {"seed": seed, "status": "skipped", "seconds": 0.0,
                "reason": f"{need} not on this checkout"}
    cmd = command(seed, floor)
    env = dict(os.environ, GEMINI_MODE="off", PYTHONPATH=str(root))
    start = time.monotonic()
    try:
        proc = runner(cmd, check=False, cwd=root, env=env, capture_output=True, text=True,
                      timeout=timeout)
        status = "pass" if proc.returncode == 0 else "fail"
        reason = _reason(_text(proc.stdout) + "\n" + _text(proc.stderr)
                         if status == "fail" and not _text(proc.stdout).strip()
                         else _text(proc.stdout))
    except subprocess.TimeoutExpired as exc:
        status, reason = "timeout", f"no result after {timeout:g} s: " + _reason(_text(exc.stdout))
    return {"seed": seed, "status": status, "seconds": round(time.monotonic() - start, 1),
            "reason": reason}


def sweep(seeds, timeout=600, root=ROOT, runner=subprocess.run, floor=None):
    """Run every seed; return (results, success_rate or None when nothing ran)."""
    results = [run_seed(s, timeout, root, runner, floor) for s in seeds]
    ran = [r for r in results if r["status"] != "skipped"]
    rate = sum(r["status"] == "pass" for r in ran) / len(ran) if ran else None
    return results, rate


def section(results, rate, floor=None):
    passed = sum(r["status"] == "pass" for r in results)
    ran = sum(r["status"] != "skipped" for r in results)
    line = (f"Success rate: {passed}/{ran} = {rate:.0%} (GEMINI_MODE=off, --auto-approve)."
            if rate is not None else
            f"Success rate: n/a, all {len(results)} seeds skipped.")
    begin, end = markers(floor)
    title = "e2e rescue" if floor is None else f"L1 -> {floor} descent, sim.demo_descent"
    line = line.replace("--auto-approve", "--auto-approve" if floor is None else "unscripted")
    rows = [begin, f"## Seed sweep ({title})", "", line, "",
            "| Seed | Result | Seconds | Reason / tail |", "|---|---|---|---|"]
    rows += [f"| {r['seed']} | {r['status'].upper()} | {r['seconds']} | {r['reason']} |"
             for r in results]
    return "\n".join([*rows, end]) + "\n"


def write_section(path, text, floor=None):
    """Replace this sweep's section in path, append it, or create the file."""
    begin, end = markers(floor)
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text() if path.exists() else ""
    if begin in old and end in old:
        head, rest = old.split(begin, 1)
        new = head + text + rest.split(end, 1)[1].lstrip("\n")
    else:
        new = old + ("\n" if old and not old.endswith("\n") else "") + \
            ("\n" if old else "") + text
    path.write_text(new)


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", default="0,1,2,3,4", help="comma list or a-b range")
    ap.add_argument("--timeout", type=float, default=600, help="seconds per seed")
    ap.add_argument("--floor", choices=DESCENT_FLOORS,
                    help="sweep the L1 -> FLOOR descent instead of the e2e rescue")
    ap.add_argument("--output", default="runs/full_test.md")
    ap.add_argument("--descent-child", choices=DESCENT_FLOORS, help=argparse.SUPPRESS)
    ap.add_argument("--seed", type=int, default=0, help=argparse.SUPPRESS)
    return ap.parse_args(argv)


def seeds_from(text):
    if "-" in text and "," not in text:
        a, b = text.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(s) for s in text.split(",") if s.strip()]


def main(argv=None, root=ROOT, runner=subprocess.run):
    args = parse(argv)
    if args.descent_child:
        return descent_child(args.descent_child, args.seed)
    results, rate = sweep(seeds_from(args.seeds), args.timeout, root, runner, args.floor)
    for r in results:
        print(f"seed {r['seed']}: {r['status'].upper()} {r['reason']}", flush=True)
    out = pathlib.Path(args.output)
    out = out if out.is_absolute() else root / out
    write_section(out, section(results, rate, args.floor), args.floor)
    print(f"wrote {out}")
    return 0 if all(r["status"] in ("pass", "skipped") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
