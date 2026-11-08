"""RESCUE-RUNNER: chain the real basement rescues B1 > B2 > B3, each with a slab shift, into one log.

    GEMINI_MODE=off python tools/run_chain.py            # prints each leg, writes runs/chain-<seed>.jsonl
    GEMINI_MODE=off python tools/run_chain.py --floors B1,B2

Each leg is tools/run_b2.py's real run for that floor (run(floor=...)), unchanged: the Scout finds its
own way down from L1 to the floor's casualty, a slab lands on its planned route there, and the leg's
nine checks (stop short, slab mapped from the Scout's own measurements, re-plan avoids it, casualty
reached, no teleport, ...) are evaluated by run_b2.evaluate. This runner adds no physics or planning.

runs/chain-<seed>.jsonl: a "meta" line, then every record of every leg in order with "leg": floor
added and "t" made cumulative across legs (chain time; the leg's own sim time is kept as "leg_t"),
a "leg" record when each leg ends (casualty, reached, passed/failed counts), then one "step" record
per check named "<floor>: <check>", and a "summary". tools/rescue_report.py reads it as is.
Exit 0 only if every check of every leg passed.
"""

import argparse
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FLOORS = ("B1", "B2", "B3")
CASUALTY = {"B1": "c1", "B2": "c2", "B3": "c3"}


def leg_records(path):
    """A leg's own log minus its trailing verdict line, which the chain re-states as steps."""
    recs = [json.loads(x) for x in pathlib.Path(path).read_text().splitlines() if x.strip()]
    return [r for r in recs if r.get("kind") != "verdict"]


def chain(legs, seed=0):
    """legs: [(floor, records, verdict)] -> one list of chained records (pure; testable)."""
    out = [{"t": 0.0, "kind": "meta", "seed": seed, "legs": [f for f, _, _ in legs],
            "source": "tools/run_chain.py"}]
    offset, steps = 0.0, []
    for floor, records, verdict in legs:
        end = max((r.get("t") or 0.0 for r in records), default=0.0)
        for r in records:
            if r.get("kind") == "summary":
                r = {**r, "kind": "leg_summary"}
            out.append({**r, "t": round(offset + (r.get("t") or 0.0), 2), "leg_t": r.get("t"), "leg": floor})
        reached = bool(next((r for r in records if r.get("kind") == "summary"), {}).get("reached"))
        out.append({"t": round(offset + end, 2), "kind": "leg", "floor": floor, "casualty": CASUALTY[floor],
                    "reached": reached, "passed": len(verdict["passed"]), "failed": len(verdict["failed"])})
        steps += [(f"{floor}: {name}", s["ok"], s.get("detail", "")) for name, s in verdict["steps"].items()]
        offset += end
    t_end = round(offset, 2)
    out += [{"t": t_end, "kind": "step", "name": n, "ok": bool(ok), "detail": d} for n, ok, d in steps]
    failed = [n for n, ok, _ in steps if not ok]
    out.append({"t": t_end, "kind": "summary", "legs": len(legs), "checks": len(steps),
                "passed": len(steps) - len(failed), "failed": failed})
    return out


def run(seed=0, floors=FLOORS, max_t=500.0, verbose=False):
    from tools import run_b2

    legs = []
    with tempfile.TemporaryDirectory() as tmp:
        for floor in floors:
            verdict, path = run_b2.run(seed=seed, max_t=max_t, out_dir=tmp, verbose=verbose, floor=floor)
            legs.append((floor, leg_records(path), verdict))
            print(f"  leg {floor}: {len(verdict['passed'])}/{len(verdict['steps'])} checks passed", flush=True)
    return chain(legs, seed)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--floors", default=",".join(FLOORS), help="comma list, in order (default B1,B2,B3)")
    p.add_argument("--max-t", type=float, default=500.0, help="sim seconds allowed per leg")
    p.add_argument("--out", default=None, help="default runs/chain-<seed>.jsonl")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args(argv)
    floors = [f.strip() for f in a.floors.split(",") if f.strip()]
    bad = [f for f in floors if f not in FLOORS]
    if bad:
        raise SystemExit(f"unknown floor(s): {bad}; choose from {list(FLOORS)}")
    records = run(a.seed, floors, a.max_t, a.verbose)
    out = pathlib.Path(a.out or ROOT / "runs" / f"chain-{a.seed}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records))
    s = records[-1]
    for r in records:
        if r["kind"] == "step" and not r["ok"]:
            print(f"  FAIL {r['name']}: {r['detail']}")
    print(f"{s['passed']}/{s['checks']} checks passed over {s['legs']} legs  log: {out.name}")
    return 0 if not s["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
