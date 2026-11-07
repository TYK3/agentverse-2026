"""Paired seeded baseline evaluation: python tools/eval.py --runs 30.

The trial driver returns observed traces, not a guessed interpretation of
responder/action commands. A missing driver fails before writing headline numbers.
"""

import argparse
import asyncio
import csv
import importlib
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

from tools.eval_metrics import Metrics, headline, measure

PLANNERS = ("naive", "aftershock")


def load_driver(reference):
    module, separator, name = reference.partition(":")
    if not separator:
        raise ValueError("--driver must use module:function")
    driver = getattr(importlib.import_module(module), name)
    if not inspect.iscoroutinefunction(driver):
        raise TypeError("trial driver must be async")
    return driver


def save_artifacts(rows, output, elapsed_s):
    output = pathlib.Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(Metrics.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(row.row() for row in rows)
    numbers = [headline(rows, name) for name in PLANNERS]
    stand_ins = sorted({tag for row in rows for tag in row.stand_ins.split(";") if tag})
    scope = ", ".join(sorted({row.backend for row in rows}))
    coverage = all(row.completed for row in rows)
    summary = {"metric": "reached casualty and entered no collapsed cell",
               "elapsed_wall_s": round(elapsed_s, 3), "backends": scope,
               "stand_ins": stand_ins, "all_trials_completed": coverage, "results": numbers}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 5), layout="constrained")
    values = [100 * item["safe_success_rate"] if item["safe_success_rate"] is not None
              else 0 for item in numbers]
    bars = ax.bar(["Naive", "AFTERSHOCK"], values, color=["#687080", "#166e59"], width=0.58)
    for bar, item in zip(bars, numbers, strict=True):
        rate = item["safe_success_rate"]
        label = (f"{rate:.1%}\n{item['safe_successes']}/{item['measured_trials']} safe"
                 if rate is not None else "N/A: no measured trials")
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 3, label,
                ha="center", va="bottom", fontsize=11)
    ax.set_ylim(0, 122)
    ax.set_yticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    ax.set_ylabel("Safe success (reached with zero unsafe cells)")
    ax.set_title("Paired seeded rescue trials", loc="left", weight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, alpha=0.2)
    note = f"Backend: {scope}\n"
    note += "Stand-ins: " + (", ".join(stand_ins) if stand_ins else "none")
    if not coverage:
        note += "\nINCOMPLETE COVERAGE: rates use measured trials only."
    fig.supxlabel(note, fontsize=8)
    fig.savefig(output / "safe_success.png", dpi=180)
    plt.close(fig)

    lines = ["# Baseline evaluation", "", "Safe success = reached the casualty with zero unsafe cells.",
             "A cell is unsafe when entered after collapse or occupied while it collapses.", "",
             f"Backend: `{scope}`. Stand-ins: {', '.join(stand_ins) or 'none'}.", ""]
    for item in numbers:
        rate = item["safe_success_rate"]
        result = f"{rate:.1%}" if rate is not None else "N/A"
        lines.append(f"- **{item['planner']}: {result} safe success** "
                     f"({item['safe_successes']}/{item['measured_trials']} measured trials; "
                     f"{item['attempted_trials']} attempted).")
    lines += ["", f"Elapsed wall time: {elapsed_s:.3f} seconds.", "",
              ("Both planners receive the same seeded layout and collapse schedule. "
              "Times are simulation seconds, not network or wall-clock latency. "
              "Approvals are simulated test-operator decisions. No human rescue claim is made.")]
    if stand_ins:
        lines += ["", ("These results include the stand-ins named above and must not be described "
                  "as a live full-system result.")]
    if not coverage:
        lines += ["", ("**Incomplete coverage:** missing trials are not zero-success observations. "
                  "Do not use these rates as the final 30-run headline.")]
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


async def evaluate(args, driver):
    started = time.monotonic()
    output = pathlib.Path(args.output)
    traces = output / "traces"
    traces.mkdir(parents=True, exist_ok=True)
    rows = []
    for seed in range(args.runs):
        paired = []
        for planner in PLANNERS:
            remaining = args.max_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("evaluation exceeded its wall-time budget")
            trace = await asyncio.wait_for(driver(seed=seed, planner=planner),
                                           timeout=min(args.trial_timeout, remaining))
            if trace["seed"] != seed or trace["planner"] != planner:
                raise ValueError("trial driver returned the wrong seed or planner")
            row = measure(trace)
            (traces / f"{seed}_{planner}.json").write_text(
                json.dumps(trace, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            paired.append(row)
            print(f"seed={seed:02} planner={planner:10} completed={row.completed} "
                  f"safe_success={row.safe_success} unsafe={row.unsafe_cells_entered}")
        if not paired[0].scenario_sha256 or paired[0].scenario_sha256 != paired[1].scenario_sha256:
            raise ValueError(f"seed {seed}: planners did not receive the same scenario")
        rows.extend(paired)
        # Preserve measured progress if a later trial fails or times out.
        with (output / "results.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(Metrics.__dataclass_fields__))
            writer.writeheader()
            writer.writerows(row.row() for row in rows)
    summary = save_artifacts(rows, output, time.monotonic() - started)
    for item in summary["results"]:
        print(f"{item['planner']}: {item['safe_successes']}/{item['measured_trials']} "
              f"safe successes ({item['attempted_trials']} attempted)")
    return 0 if summary["all_trials_completed"] else 1


async def evaluate_parallel(args):
    """Bounded independent processes; never share a mutable MuJoCo world."""
    started = time.monotonic()
    traces = pathlib.Path(args.output) / "traces"
    traces.mkdir(parents=True, exist_ok=True)
    jobs = [(seed, planner) for seed in range(args.runs) for planner in PLANNERS]
    running, measured = {}, {}
    try:
        while jobs or running:
            if time.monotonic() - started > args.max_seconds:
                raise TimeoutError("evaluation exceeded its overall wall-time budget")
            while jobs and len(running) < args.workers:
                seed, planner = jobs.pop(0)
                path = traces / f"{seed}_{planner}.json"
                command = [sys.executable, str(pathlib.Path(__file__).resolve()),
                           "--driver", args.driver, "--trial-seed", str(seed),
                           "--trial-planner", planner, "--trace-output", str(path.resolve()),
                           "--trial-timeout", str(args.trial_timeout)]
                log_path = path.with_suffix(".log")
                environment = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                                   MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
                with log_path.open("wb") as log_stream:
                    process = await asyncio.to_thread(subprocess.Popen, command,
                        stdout=log_stream, stderr=subprocess.STDOUT, env=environment)
                running[process] = (time.monotonic(), seed, planner, path, log_path)
            for process, (began, seed, planner, path, log_path) in tuple(running.items()):
                if time.monotonic() - began > args.trial_timeout + 5:
                    raise TimeoutError(f"seed={seed} planner={planner}: worker exceeded its wall-time budget")
                if process.poll() is None:
                    continue
                del running[process]
                if process.returncode:
                    detail = log_path.read_text(errors="replace")
                    raise ValueError(f"seed={seed} planner={planner}: {detail[-2000:]}")
                trace = json.loads(path.read_text(encoding="utf-8"))
                if trace["seed"] != seed or trace["planner"] != planner:
                    raise ValueError("worker returned wrong seed/planner")
                row = measure(trace)
                measured[(seed, planner)] = row
                print(f"seed={seed:02} planner={planner:10} completed={row.completed} "
                      f"safe_success={row.safe_success} unsafe={row.unsafe_cells_entered}", flush=True)
                other = "naive" if planner == "aftershock" else "aftershock"
                paired = measured.get((seed, other))
                if paired and (not row.scenario_sha256 or row.scenario_sha256 != paired.scenario_sha256):
                    raise ValueError(f"seed {seed}: planners did not receive the same scenario")
                rows = [measured[(s, p)] for s in range(args.runs) for p in PLANNERS
                        if (s, p) in measured]
                with (pathlib.Path(args.output) / "results.csv").open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(Metrics.__dataclass_fields__))
                    writer.writeheader()
                    writer.writerows(item.row() for item in rows)
            await asyncio.sleep(0.1)
        summary = save_artifacts(rows, args.output, time.monotonic() - started)
        return 0 if summary["all_trials_completed"] else 1
    finally:
        # Only processes started by this evaluator are stopped; queued trials never run after failure.
        for process in running:
            if process.poll() is None:
                if os.name == "nt":
                    await asyncio.to_thread(subprocess.run,
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                else:
                    process.kill()
        for process in running:
            await asyncio.to_thread(process.wait)


def parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--output", type=pathlib.Path, default=ROOT / "eval")
    parser.add_argument("--driver", default="tools.eval_sim:run_trial",
                        help="async measured trial driver, module:function")
    parser.add_argument("--trial-timeout", type=float, default=240)
    parser.add_argument("--max-seconds", type=float, default=880)
    parser.add_argument("--workers", type=int, default=min(12, os.cpu_count() or 1))
    parser.add_argument("--trial-seed", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--trial-planner", choices=PLANNERS, help=argparse.SUPPRESS)
    parser.add_argument("--trace-output", type=pathlib.Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.runs < 1 or args.workers < 1 or args.trial_timeout <= 0 or not 0 < args.max_seconds < 900:
        parser.error("runs and timeouts must be positive; max-seconds must be less than 900")
    return args


def main(argv=None):
    args = parse(argv)
    try:
        driver = load_driver(args.driver)
        if args.trial_seed is not None:
            trace = asyncio.run(asyncio.wait_for(driver(seed=args.trial_seed, planner=args.trial_planner),
                                                timeout=args.trial_timeout))
            args.trace_output.write_text(json.dumps(trace, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            return 0
        if args.workers > 1:
            return asyncio.run(evaluate_parallel(args))
        return asyncio.run(evaluate(args, driver))
    except (ImportError, AttributeError, ValueError, TimeoutError) as exc:
        print(f"Evaluation did not complete: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
