"""RESCUE-REPORT: one-page markdown summary of a real run log.

    python tools/rescue_report.py runs/levels-0.jsonl            # -> runs/levels-0.md
    python tools/rescue_report.py runs/b2-0.jsonl --out -        # print instead

Reads the {"t": sim seconds, "kind": ...} JSONL written by tools/run_levels.py (B1 > B2 > B3) or
tools/run_b2.py (B2 with a slab shift) and writes: the verdict, each check with its detail, when
each floor was reached, each casualty leg with its time and planning effort, the slab shift if
there was one, and the run's summary numbers. It only reads the log (sim seconds, never wall time),
so the same log always gives the same page. Exit 0 if every check in the log passed, 1 if any
failed, 2 if the log has no checks.
"""

import argparse
import collections
import json
import pathlib
import sys


def load(path):
    return [json.loads(line) for line in pathlib.Path(path).read_text().splitlines() if line.strip()]


def checks(records):
    """[(name, ok, t or None, detail)] from "step" records (run_levels) or a "verdict" (run_b2)."""
    steps = [r for r in records if r.get("kind") == "step"]
    if steps:
        return [(r["name"], bool(r["ok"]), None, r.get("detail", "")) for r in steps]   # t = end of run
    verdict = next((r for r in records if r.get("kind") == "verdict"), None)
    if verdict:
        return [(n, bool(s["ok"]), s.get("t"), s.get("detail", "")) for n, s in verdict["steps"].items()]
    return []


def floors(records):
    """[(level, t first reached)] in order."""
    return [(r["level"], r["t"]) for r in records if r.get("kind") == "level"]


def legs(records):
    """Casualty legs with start, end, duration and plan counts by reason (run_levels logs)."""
    plans = collections.defaultdict(collections.Counter)
    for r in records:
        if r.get("kind") == "plan" and "leg" in r:
            plans[r["leg"]][r.get("why", "?")] += 1
    out, start = [], 0.0
    for r in records:
        if r.get("kind") != "leg":
            continue
        out.append({"floor": r["floor"], "casualty": r.get("casualty", "?"), "reached": r["reached"],
                    "start": start, "end": r["t"], "seconds": round(r["t"] - start, 1),
                    "plans": dict(plans[r["floor"]]), "stuck": r.get("stuck")})
        start = r["t"]
    return out


def _t(t):
    return f"{t:.1f} s" if isinstance(t, (int, float)) else "-"


def _cell(text):
    return str(text).replace("|", "/").replace("\n", " ")


def report(records, name="run"):
    meta = next((r for r in records if r.get("kind") == "meta"), {})
    summary = next((r for r in records if r.get("kind") == "summary"), {})
    cs = checks(records)
    passed = sum(ok for _, ok, _, _ in cs)
    end = max((r.get("t", 0) or 0 for r in records), default=0)
    verdict = ("no checks in this log" if not cs else
               f"**{'PASS' if passed == len(cs) else 'FAIL'}**: {passed}/{len(cs)} checks passed")
    src = meta.get("source") or ("tools/run_b2.py" if any(r.get("kind") == "shift" for r in records) else "?")
    out = [f"# Rescue report: {name}", "",
           (f"{verdict}. Source {src}, seed {meta.get('seed', '-')}, {_t(end)} of sim time, "
           f"{sum(r.get('kind') == 'plan' for r in records)} planner decisions; "
           "times are sim seconds."), "", "## Checks", "", "| | Check | At | Detail |", "|---|---|---|---|"]
    out += [f"| {'ok' if ok else 'FAIL'} | {_cell(n)} | {_t(t)} | {_cell(d)} |" for n, ok, t, d in cs]
    fl = floors(records)
    if fl:
        out += ["", "## Floors", "", " > ".join(f"{lv} ({_t(t)})" for lv, t in fl)]
    lg = legs(records)
    if lg:
        out += ["", "## Casualty legs", "", "| Leg | Casualty | Reached | From | To | Took | Plans |",
                "|---|---|---|---|---|---|---|"]
        for x in lg:
            plans = ", ".join(f"{k} {v}" for k, v in sorted(x["plans"].items())) or "-"
            reached = "yes" if x["reached"] else f"no{': ' + _cell(x['stuck']) if x['stuck'] else ''}"
            out.append(f"| {x['floor']} | {x['casualty']} | {reached} | {_t(x['start'])} | {_t(x['end'])} | "
                       f"{_t(x['seconds'])} | {plans} |")
    shift = next((r for r in records if r.get("kind") == "shift"), None)
    if shift:
        out += ["", "## World change", "",
                f"Slab dropped at {_t(shift['t'])} on {shift.get('level', '?')} at {shift.get('xy')}."]
    if summary:
        keep = {k: v for k, v in summary.items() if k not in ("t", "kind")}
        out += ["", "## Summary", "", "| Field | Value |", "|---|---|"]
        out += [f"| {k} | {_cell(json.dumps(v))} |" for k, v in keep.items()]
    return "\n".join(out) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("log", help="a run log, e.g. runs/levels-0.jsonl")
    p.add_argument("--out", default=None, help="markdown path (default: next to the log), - for stdout")
    a = p.parse_args(argv)
    path = pathlib.Path(a.log)
    records = load(path)
    text = report(records, path.stem)
    if a.out == "-":
        print(text, end="")
    else:
        out = pathlib.Path(a.out) if a.out else path.with_suffix(".md")
        out.write_text(text)
        print(f"wrote {out}")
    cs = checks(records)
    return 2 if not cs else (0 if all(ok for _, ok, _, _ in cs) else 1)


if __name__ == "__main__":
    sys.exit(main())
