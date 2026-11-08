"""B1-RUN-LOG: record one real B1 rescue run as a console fixture.

    GEMINI_MODE=off python tools/record_b1_run.py            # writes console/tests/fixtures/b1-rescue-seed0.jsonl
    python tools/record_b1_run.py --check                    # checks the recorded file only, no run

It runs tools/run_b2.py's real runner with floor B1 (LevelWorld physics, the Scout's own multi-level map
and A*; nothing scripted) and copies the jsonl it writes, unchanged, to the fixture path. Nothing is
added, faked or synthesised: the fixture holds exactly the records the runner emitted.

--check reports which rescue phases the log holds (scene load, survivor located, descent to B1,
delivery, slab shift, stop and recheck) from the records themselves, and fails if the file is over
MAX_BYTES or holds image data, base64, prompts or secrets. A missing phase is reported as a gap, not
an error: it is what the runner does not emit.
"""

import argparse
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "console" / "tests" / "fixtures" / "b1-rescue-seed0.jsonl"
MAX_BYTES = 2_000_000
LEAKS = re.compile(r"data:image|;base64,|[A-Za-z0-9+/]{200,}={0,2}|\bprompt\b|api[_-]?key|secret|password|"
                   r"bearer |AIza[0-9A-Za-z_-]{10,}|sk-[A-Za-z0-9]{16,}", re.IGNORECASE)


def phases(records):
    """Each rescue phase -> the evidence for it in the records, or None when the runner emits none."""
    kinds = {r["kind"] for r in records}
    levels = [r["level"] for r in records if r["kind"] == "level"]
    summary = next((r for r in records if r["kind"] == "summary"), {})
    shift = next((r for r in records if r["kind"] == "shift"), None)
    steps = next((r for r in records if r["kind"] == "verdict"), {}).get("steps", {})
    stop = steps.get("Scout stopped short of the slab", {})
    replan = steps.get("re-planned route avoids the slab", {})
    return {
        "scene load": "scene/loaded" if kinds & {"scene", "scene/loaded", "meta"} else None,
        "survivor located": (f"reached c1 at {summary.get('final_pos')} on {summary.get('final_level')}"
                             if summary.get("reached") else None),
        "descent to B1": " > ".join(levels) if levels[-1:] == ["B1"] else None,
        "delivery": "delivery" if kinds & {"delivery", "responder/action", "place_supply"} else None,
        "slab shift": f"slab at {shift['xy']} on {shift['level']}" if shift else None,
        "stop and recheck": (f"stop: {stop.get('detail')}; recheck: {replan.get('detail')}"
                             if stop.get("ok") and replan.get("ok") else None),
    }


def check(path=FIXTURE):
    """Print the phases and gaps; return 0 when the file is sane (size, no leaks), else 1."""
    text = pathlib.Path(path).read_text(encoding="utf-8")
    records = [json.loads(line) for line in text.splitlines() if line.strip()]
    size, problems = len(text.encode()), []
    if size > MAX_BYTES:
        problems.append(f"{size} bytes > {MAX_BYTES}")
    for n, line in enumerate(text.splitlines(), 1):
        m = LEAKS.search(line)
        if m:
            problems.append(f"line {n}: looks like image/prompt/secret data ({m.group(0)[:20]!r})")
    print(f"{path}: {len(records)} records, {size} bytes")
    for name, evidence in phases(records).items():
        print(f"  {'present' if evidence else 'GAP    '}  {name}: {evidence or 'not emitted by the runner'}")
    for p in problems:
        print(f"  FAIL {p}")
    return 1 if problems else 0


def record(seed=0, max_t=500.0, out=FIXTURE):
    os.environ.setdefault("GEMINI_MODE", "off")
    from tools.run_b2 import run

    with tempfile.TemporaryDirectory() as tmp:
        verdict, path = run(seed=seed, max_t=max_t, out_dir=tmp, floor="B1")
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, out)
    print(f"run_b2 --floor B1 seed {seed}: {len(verdict['passed'])}/{len(verdict['steps'])} steps passed; "
          f"failed: {verdict['failed'] or 'none'}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-t", type=float, default=500.0, help="sim seconds allowed")
    ap.add_argument("--output", type=pathlib.Path, default=FIXTURE)
    ap.add_argument("--check", action="store_true", help="only check the recorded file")
    args = ap.parse_args(argv)
    if not args.check:
        record(args.seed, args.max_t, args.output)
    return check(args.output)


if __name__ == "__main__":
    sys.exit(main())
