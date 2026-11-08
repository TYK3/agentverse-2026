"""One clean run of every pytest suite plus the e2e rescue: python tools/full_test.py.

Each suite runs in its own subprocess with GEMINI_MODE=off and a timeout, so one
hanging lane cannot stall the rest. The result goes to runs/full_test.md: a
pass/fail table per suite and the last lines of each suite's output.

The sim demos (descent, responder, aftershock) run headless as rows too; each
must exit 0. The e2e rescue (tools/run_rescue.py) runs only if that file exists on this
checkout; otherwise it is reported as "skipped", never as passed.
Exit code is 0 only when nothing failed or timed out.
"""

import argparse
import os
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITES = ["coord/tests", "tools/tests", "sim/tests", "perception/tests", "planner", "voice/tests"]
DEMOS = [("sim.demo_descent", []), ("sim.demo_responder", ["--headless"]),
         ("sim.demo_aftershock", ["--no-viewer"])]
RESCUE = "tools/run_rescue.py"
TAIL_LINES = 25
_SUMMARY = re.compile(r"^=*\s*(\d+ (?:passed|failed|errors?|skipped|deselected)\b.*?) in [\d.]+s",
                      re.MULTILINE)


def run(name, cmd, timeout, cwd=ROOT):
    """Run one command; return a result dict (status pass/fail/timeout)."""
    env = dict(os.environ, GEMINI_MODE="off", PYTHONPATH=str(cwd))
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, check=False, cwd=cwd, env=env, capture_output=True, text=True,
                              timeout=timeout)
        out, status = proc.stdout + proc.stderr, "pass" if proc.returncode == 0 else "fail"
        code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        out = _text(exc.stdout) + _text(exc.stderr)
        status, code = "timeout", None
    return {"name": name, "cmd": " ".join(cmd), "status": status, "code": code,
            "seconds": round(time.monotonic() - start, 1), "summary": summary(out),
            "tail": "\n".join(out.rstrip().splitlines()[-TAIL_LINES:])}


def _text(data):
    if data is None:
        return ""
    return data.decode(errors="replace") if isinstance(data, bytes) else data


def summary(output):
    """The pytest one-line summary, e.g. '90 passed, 1 skipped', or ''."""
    found = _SUMMARY.findall(output)
    return found[-1] if found else ""


def skipped(name, why):
    return {"name": name, "cmd": "", "status": "skipped", "code": None, "seconds": 0.0,
            "summary": why, "tail": ""}


def plan(root, suites, seed, rescue_timeout, demos=True):
    """List of (name, cmd, timeout|None) jobs; None cmd means skipped with a reason."""
    jobs = []
    for suite in suites:
        if (root / suite).exists():
            jobs.append((suite, [sys.executable, "-m", "pytest", suite, "-q",
                                 "-p", "no:cacheprovider"], None))
        else:
            jobs.append((suite, None, "folder not on this checkout"))
    for module, flags in DEMOS if demos else []:
        name = " ".join([module, *flags])
        if (root / (module.replace(".", "/") + ".py")).exists():
            jobs.append((name, [sys.executable, "-m", module, *flags], rescue_timeout))
        else:
            jobs.append((name, None, "module not on this checkout"))
    if (root / RESCUE).exists():
        jobs.append((f"e2e rescue (seed {seed})",
                     [sys.executable, RESCUE, "--auto-approve", "--seed", str(seed)],
                     rescue_timeout))
    else:
        jobs.append(("e2e rescue", None, f"{RESCUE} not on this checkout"))
    return jobs


def report(results, started):
    counts = {s: sum(r["status"] == s for r in results)
              for s in ("pass", "fail", "timeout", "skipped")}
    lines = ["# Full test run", "",
             (f"Started {started}, GEMINI_MODE=off. "
              f"pass {counts['pass']}, fail {counts['fail']}, timeout {counts['timeout']}, "
              f"skipped {counts['skipped']}."), "",
             "| Suite | Result | Summary | Seconds |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['name']} | {r['status'].upper()} | {r['summary'] or '-'} | "
                     f"{r['seconds']} |")
    for r in results:
        if r["status"] == "skipped":
            continue
        lines += ["", f"## {r['name']}: {r['status']}", "", f"`{r['cmd']}`", "",
                  "```", r["tail"] or "(no output)", "```"]
    return "\n".join(lines) + "\n"


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--timeout", type=float, default=600, help="seconds per pytest suite")
    ap.add_argument("--rescue-timeout", type=float, default=300, help="seconds for each demo and the e2e run")
    ap.add_argument("--seed", type=int, default=1, help="seed for the e2e rescue")
    ap.add_argument("--suite", action="append", help="only these suites (repeatable)")
    ap.add_argument("--no-rescue", action="store_true", help="skip the e2e rescue")
    ap.add_argument("--no-demos", action="store_true", help="skip the sim demo rows")
    ap.add_argument("--output", default="runs/full_test.md")
    return ap.parse_args(argv)


def main(argv=None, root=ROOT):
    args = parse(argv)
    started = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    results = []
    for name, cmd, extra in plan(root, args.suite or SUITES, args.seed, args.rescue_timeout,
                                  not args.no_demos):
        if name.startswith("e2e") and args.no_rescue:
            results.append(skipped(name, "--no-rescue"))
        elif cmd is None:
            results.append(skipped(name, extra))
        else:
            results.append(run(name, cmd, extra or args.timeout, cwd=root))
        r = results[-1]
        print(f"{r['status'].upper():8} {r['name']} {r['summary']}", flush=True)
    out = pathlib.Path(args.output)
    out = out if out.is_absolute() else root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report(results, started))
    print(f"wrote {out}")
    return 0 if all(r["status"] in ("pass", "skipped") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
