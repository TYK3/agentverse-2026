"""E2E rescue over several seeds with a success-rate table: python tools/seed_sweep.py.

Each seed runs `tools/run_rescue.py --auto-approve --seed N` in its own subprocess with
GEMINI_MODE=off and a timeout. Assumed interface (from #52's branch): exit 0 when every
step passed, 1 otherwise; the last stdout line reads "K/M steps passed[; failed: ...]";
the bus log goes to runs/rescue-<seed>.jsonl. If the script is missing, every seed is
SKIPPED with the reason, never passed.

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


def _text(data):
    if data is None:
        return ""
    return data.decode(errors="replace") if isinstance(data, bytes) else data


def _reason(output, limit=120):
    lines = [ln.strip() for ln in output.strip().splitlines() if ln.strip()]
    text = lines[-1] if lines else "(no output)"
    return text.replace("|", "/")[:limit]


def run_seed(seed, timeout, root=ROOT, runner=subprocess.run):
    """One seed: dict with seed, status (pass/fail/timeout/skipped), seconds, reason."""
    if not (root / RESCUE).exists():
        return {"seed": seed, "status": "skipped", "seconds": 0.0,
                "reason": f"{RESCUE} not on this checkout"}
    cmd = [sys.executable, RESCUE, "--auto-approve", "--seed", str(seed)]
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


def sweep(seeds, timeout=600, root=ROOT, runner=subprocess.run):
    """Run every seed; return (results, success_rate or None when nothing ran)."""
    results = [run_seed(s, timeout, root, runner) for s in seeds]
    ran = [r for r in results if r["status"] != "skipped"]
    rate = sum(r["status"] == "pass" for r in ran) / len(ran) if ran else None
    return results, rate


def section(results, rate):
    passed = sum(r["status"] == "pass" for r in results)
    ran = sum(r["status"] != "skipped" for r in results)
    line = (f"Success rate: {passed}/{ran} = {rate:.0%} (GEMINI_MODE=off, --auto-approve)."
            if rate is not None else
            f"Success rate: n/a, all {len(results)} seeds skipped.")
    rows = [BEGIN, "## Seed sweep (e2e rescue)", "", line, "",
            "| Seed | Result | Seconds | Reason / tail |", "|---|---|---|---|"]
    rows += [f"| {r['seed']} | {r['status'].upper()} | {r['seconds']} | {r['reason']} |"
             for r in results]
    return "\n".join([*rows, END]) + "\n"


def write_section(path, text):
    """Replace the SEED-SWEEP section in path, append it, or create the file."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text() if path.exists() else ""
    if BEGIN in old and END in old:
        head, rest = old.split(BEGIN, 1)
        tail = rest.split(END, 1)[1].lstrip("\n")
        new = head + text + tail
    else:
        new = old + ("\n" if old and not old.endswith("\n") else "") + \
            ("\n" if old else "") + text
    path.write_text(new)


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", default="0,1,2,3,4", help="comma list or a-b range")
    ap.add_argument("--timeout", type=float, default=600, help="seconds per seed")
    ap.add_argument("--output", default="runs/full_test.md")
    return ap.parse_args(argv)


def seeds_from(text):
    if "-" in text and "," not in text:
        a, b = text.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(s) for s in text.split(",") if s.strip()]


def main(argv=None, root=ROOT, runner=subprocess.run):
    args = parse(argv)
    results, rate = sweep(seeds_from(args.seeds), args.timeout, root, runner)
    for r in results:
        print(f"seed {r['seed']}: {r['status'].upper()} {r['reason']}", flush=True)
    out = pathlib.Path(args.output)
    out = out if out.is_absolute() else root / out
    write_section(out, section(results, rate))
    print(f"wrote {out}")
    return 0 if all(r["status"] in ("pass", "skipped") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
