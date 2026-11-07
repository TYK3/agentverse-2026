"""Replay a recorded sensors/scout stream into the map and check the seen count only rises (T08).

    python -m perception.replay [recording.jsonl] [--out map_cells.json]

Default recording: sim/recordings/scout_backup.jsonl (T04). Until that lands, the stand-in
perception/fixtures/scout_backup_standin.jsonl, ray-cast from the backup scene by
perception/fixtures/make_standin.py.
"""

import argparse
import itertools
import json
import pathlib
import sys

from perception.grid import Grid

ROOT = pathlib.Path(__file__).resolve().parent.parent
RECORDING = ROOT / "sim" / "recordings" / "scout_backup.jsonl"
STANDIN = ROOT / "perception" / "fixtures" / "scout_backup_standin.jsonl"


def frames(path):
    """sensors/scout payloads from a JSON-lines file of bus messages or bare payloads."""
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            msg = json.loads(line)
            if "topic" in msg:
                if msg["topic"] != "sensors/scout":
                    continue
                msg = msg["data"]
            yield msg


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, help="write the final map/cells snapshot here")
    args = ap.parse_args(argv)
    path = args.path or (RECORDING if RECORDING.exists() else STANDIN)
    if path == STANDIN:
        print(f"using the STAND-IN recording {STANDIN.relative_to(ROOT)}, not T04's {RECORDING.relative_to(ROOT)}")

    grid, seen, t = Grid(), [], 0.0
    for data in frames(path):
        grid.add_sensors(data)
        seen.append(grid.counts()["seen"])
        t = data.get("t", t)
    if not seen:
        print(f"no sensors/scout frames in {path}")
        return 1

    rising = all(a <= b for a, b in itertools.pairwise(seen))
    c = grid.counts()
    print(f"{len(seen)} frames: seen {seen[0]} -> {seen[-1]}, inferred {c['inferred']}, "
          f"occupied {c['occupied']}, seen count only rises: {'yes' if rising else 'NO'}")
    if args.out:
        args.out.write_text(json.dumps(grid.snapshot(t)))
        print(f"wrote {args.out}")
    return 0 if rising else 1


if __name__ == "__main__":
    sys.exit(main())
