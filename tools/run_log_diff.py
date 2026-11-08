"""RUN-LOG-DIFF: compare two real run logs and say where they part.

    python tools/run_log_diff.py runs/chain-0.jsonl runs/chain-0.again.jsonl
    python tools/run_log_diff.py a.jsonl b.jsonl --ignore pose --t-tol 0.5 --pos-tol 0.02

Reads any {"t", "kind" (or "topic"), ...} JSONL the runners write (run_levels, run_chain, run_b2,
demo60, the sim recorder). Prints: record counts per kind on each side, the checks that changed
(a "step" record's ok or a run_b2 "verdict"), and the first record where the two logs diverge,
comparing in order with numbers allowed to differ by --t-tol for times and --pos-tol for other
floats (wall-clock fields are always ignored). Same logs -> exit 0; any difference -> exit 1.
"""

import argparse
import collections
import json
import math
import pathlib
import sys

WALL = {"wall", "wall_s", "seconds", "started"}


def load(path):
    return [json.loads(x) for x in pathlib.Path(path).read_text().splitlines() if x.strip()]


def kind(r):
    return r.get("kind") or r.get("topic") or "?"


def checks(records):
    """{name: ok} from "step" records or a run_b2 "verdict"."""
    out = {r["name"]: bool(r["ok"]) for r in records if r.get("kind") == "step"}
    for r in records:
        if r.get("kind") == "verdict":
            out.update({n: bool(s["ok"]) for n, s in r.get("steps", {}).items()})
    return out


def same(a, b, t_tol, pos_tol, key=""):
    """True if a and b match: equal structure, floats within tolerance, wall fields ignored."""
    if isinstance(a, dict) and isinstance(b, dict):
        keys = (set(a) | set(b)) - WALL
        return all(same(a.get(k), b.get(k), t_tol, pos_tol, k) for k in keys)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y, t_tol, pos_tol, key) for x, y in zip(a, b, strict=True))
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        tol = t_tol if key in ("t", "leg_t", "sim_t") else pos_tol
        return math.isclose(a, b, abs_tol=tol)
    return a == b


def diff(a, b, ignore=(), t_tol=0.0, pos_tol=0.0):
    """Compare two record lists -> {"counts", "checks_changed", "first", "same"}."""
    fa = [r for r in a if kind(r) not in ignore]
    fb = [r for r in b if kind(r) not in ignore]
    ca, cb = collections.Counter(map(kind, fa)), collections.Counter(map(kind, fb))
    counts = {k: (ca.get(k, 0), cb.get(k, 0)) for k in sorted(set(ca) | set(cb)) if ca.get(k, 0) != cb.get(k, 0)}
    ka, kb = checks(a), checks(b)
    changed = {n: (ka.get(n), kb.get(n)) for n in sorted(set(ka) | set(kb)) if ka.get(n) != kb.get(n)}
    first = None
    for i in range(max(len(fa), len(fb))):
        ra = fa[i] if i < len(fa) else None
        rb = fb[i] if i < len(fb) else None
        if ra is None or rb is None or not same(ra, rb, t_tol, pos_tol):
            first = {"index": i, "a": ra, "b": rb}
            break
    return {"counts": counts, "checks_changed": changed, "first": first,
            "same": not counts and not changed and first is None, "records": (len(fa), len(fb))}


def render(d, name_a="a", name_b="b"):
    if d["same"]:
        return f"same: {d['records'][0]} records match ({name_a} vs {name_b})\n"
    out = [f"differ: {name_a} has {d['records'][0]} records, {name_b} has {d['records'][1]}"]
    for k, (x, y) in d["counts"].items():
        out.append(f"  count {k}: {x} vs {y}")
    for n, (x, y) in d["checks_changed"].items():
        out.append(f"  check {n}: {x} -> {y}")
    if d["first"]:
        f = d["first"]
        out.append(f"  first difference at record {f['index']}:")
        out.append(f"    {name_a}: {json.dumps(f['a'])[:300] if f['a'] is not None else '(end of log)'}")
        out.append(f"    {name_b}: {json.dumps(f['b'])[:300] if f['b'] is not None else '(end of log)'}")
    return "\n".join(out) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--ignore", action="append", default=[], help="record kind to skip (repeatable), e.g. pose")
    p.add_argument("--t-tol", type=float, default=0.0, help="allowed difference in sim times")
    p.add_argument("--pos-tol", type=float, default=0.0, help="allowed difference in other numbers")
    args = p.parse_args(argv)
    d = diff(load(args.a), load(args.b), set(args.ignore), args.t_tol, args.pos_tol)
    sys.stdout.write(render(d, pathlib.Path(args.a).name, pathlib.Path(args.b).name))
    return 0 if d["same"] else 1


if __name__ == "__main__":
    sys.exit(main())
