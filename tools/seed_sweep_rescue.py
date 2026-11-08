"""RESCUE-SWEEP: run the chained real rescue B1 > B2 > B3 over many seeds: python tools/seed_sweep_rescue.py --seeds 0-4

Each seed is one isolated child process of tools/run_chain.py (GEMINI_MODE=off), so a crash, hang or leaked
state in one seed cannot touch the next. The runner itself adds no physics or checks: a seed passes only if
the child exits 0, its log ends with a "summary" covering every requested leg with no failed check, and the
Scout reached the casualty on every leg ("leg" records). An exit code alone is not evidence of a rescue.

Writes, under --out-dir (default runs/): rescue-<seed>.jsonl (the chain log, as tools/rescue_report.py
reads it), rescue-<seed>.out (the child's stdout+stderr), seed_sweep_rescue.md and seed_sweep_rescue.json.
Exit 0 only if every seed passed.
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.seed_sweep import seeds_from

FLOORS = ("B1", "B2", "B3")


def records_of(path):
    try:
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return []


def verdict(returncode, records, floors):
    """(status, reason, legs) for one seed from its exit code and chain log (pure; testable)."""
    legs = [{"floor": r["floor"], "reached": bool(r.get("reached")), "passed": r.get("passed"),
             "failed": r.get("failed")} for r in records if r.get("kind") == "leg"]
    summary = records[-1] if records and records[-1].get("kind") == "summary" else None
    if summary is None:
        return "fail", "no summary in the chain log", legs
    failed = list(summary.get("failed") or [])
    if failed:
        return "fail", f"{len(failed)} failed: " + "; ".join(failed), legs
    if [leg["floor"] for leg in legs] != list(floors) or summary.get("legs") != len(floors):
        return "fail", f"legs {[leg['floor'] for leg in legs]} != {list(floors)}", legs
    missed = [leg["floor"] for leg in legs if not leg["reached"]]
    if missed:
        return "fail", f"casualty not reached on {missed}", legs
    if returncode != 0:
        return "fail", f"run_chain exited {returncode}", legs
    return "pass", f"{summary['passed']}/{summary['checks']} checks over {len(legs)} legs", legs


def run_seed(seed, floors, timeout, max_t, out_dir, runner=subprocess.run):
    log = out_dir / f"rescue-{seed}.jsonl"
    log.unlink(missing_ok=True)                    # a previous good log must not survive a failed attempt
    command = [sys.executable, str(ROOT / "tools" / "run_chain.py"), "--seed", str(seed),
               "--floors", ",".join(floors), "--max-t", str(max_t), "--out", str(log)]
    start = time.monotonic()
    try:
        proc = runner(command, cwd=ROOT, env=dict(os.environ, GEMINI_MODE="off"),
                      capture_output=True, text=True, timeout=timeout, check=False)
        code, output = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        code = None
        output = (exc.stdout or b"") + (exc.stderr or b"")
        output = output.decode(errors="replace") if isinstance(output, bytes) else output
    seconds = round(time.monotonic() - start, 2)
    (out_dir / f"rescue-{seed}.out").write_text(output, encoding="utf-8")
    records = records_of(log)
    if code is None:
        status, reason, legs = "timeout", f"no result in {timeout:g} wall seconds", verdict(1, records, floors)[2]
    else:
        status, reason, legs = verdict(code, records, floors)
    sim = records[-1]["t"] if records and records[-1].get("kind") == "summary" else None
    return {"seed": seed, "status": status, "seconds": seconds, "sim_seconds": sim, "reason": reason,
            "legs": legs, "log": log.name}


def report(results, floors):
    passed = sum(r["status"] == "pass" for r in results)
    summary = (f"rescue {'>'.join(floors)}: {passed}/{len(results)} seeds passed "
               f"({passed / len(results):.0%}), GEMINI_MODE=off")
    head = "| Seed | Result | " + " | ".join(floors) + " | Wall s | Sim s | Reason |"
    rows = ["# Rescue seed sweep", "", summary, "", head, "|---" * (len(floors) + 5) + "|"]
    for r in results:
        by_floor = {leg["floor"]: leg for leg in r["legs"]}
        cells = []
        for f in floors:
            leg = by_floor.get(f)
            cells.append("-" if leg is None else
                         f"{leg['passed']}/{leg['passed'] + leg['failed']}{'' if leg['reached'] else ' not reached'}")
        rows.append(f"| {r['seed']} | {r['status'].upper()} | " + " | ".join(cells) +
                    f" | {r['seconds']} | {r['sim_seconds']} | {r['reason']} |")
    return summary, passed, "\n".join(rows) + "\n"


def positive(value):
    number = float(value)
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return number


def main(argv=None, runner=subprocess.run):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seeds", default="0-4", help="comma list or inclusive a-b range (default 0-4)")
    p.add_argument("--floors", default=",".join(FLOORS), help="comma list, in order (default B1,B2,B3)")
    p.add_argument("--timeout", type=positive, default=1800, help="wall seconds per seed (whole chain)")
    p.add_argument("--max-t", type=positive, default=500, help="sim seconds allowed per leg")
    p.add_argument("--out-dir", type=pathlib.Path, default=ROOT / "runs")
    a = p.parse_args(argv)
    floors = [f.strip() for f in a.floors.split(",") if f.strip()]
    bad = [f for f in floors if f not in FLOORS]
    if not floors or bad:
        p.error(f"invalid --floors {bad or a.floors!r}; choose from {list(FLOORS)}")
    try:
        seeds = seeds_from(a.seeds)
        if not seeds or any(s < 0 for s in seeds) or len(set(seeds)) != len(seeds):
            raise ValueError("use distinct non-negative seeds")
    except ValueError as exc:
        p.error(f"invalid --seeds: {exc}")
    out_dir = a.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for seed in seeds:
        r = run_seed(seed, floors, a.timeout, a.max_t, out_dir, runner)
        results.append(r)
        sim = "n/a" if r["sim_seconds"] is None else f"{r['sim_seconds']}s"
        print(f"seed {seed}: {r['status'].upper()} wall={r['seconds']:.0f}s sim={sim} "
              f"{r['reason']}", flush=True)
    summary, passed, table = report(results, floors)
    print(summary)
    (out_dir / "seed_sweep_rescue.md").write_text(table, encoding="utf-8")
    (out_dir / "seed_sweep_rescue.json").write_text(json.dumps(
        {"floors": floors, "passed": passed, "total": len(results), "results": results}, indent=2) + "\n",
        encoding="utf-8")
    print(f"reports: {out_dir / 'seed_sweep_rescue.md'} and seed_sweep_rescue.json")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
