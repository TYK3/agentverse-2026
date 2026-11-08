"""Regenerate the B1 golden: python -m tools.tests.golden.make_b1 (GEMINI_MODE=off, about 15 s).

Runs the real, unscripted L1 -> B1 descent (sim.demo_descent.run(floor="B1")) and writes
tools/tests/golden/b1_descent.jsonl: a meta line, one line per planner decision in order
({"t","level","action","target","status"}, sim seconds, rounded), and a summary line.
No wall-clock times, paths or host details are stored.
"""

import json
import pathlib
import re

GOLDEN = pathlib.Path(__file__).with_name("b1_descent.jsonl")
LINE = re.compile(r"^\s*([\d.]+)s (\S+)\s+(\S+) -> \[([^\]]*)\] \((\w+)\)$")


def events(log):
    out = []
    for line in log:
        m = LINE.match(line)
        if not m:
            raise ValueError(f"unexpected log line: {line!r}")
        t, level, action, target, status = m.groups()
        out.append({"t": round(float(t), 1), "level": level, "action": action,
                    "target": [round(float(v), 2) for v in target.split(",")], "status": status})
    return out


def record(summary):
    lines = [{"kind": "meta", "floor": "B1", "source": "sim.demo_descent.run", "time": "sim seconds"}]
    lines += [{"kind": "event", **e} for e in events(summary["log"])]
    lines.append({"kind": "summary", "reached": summary["reached"], "t": summary["t"],
                  "levels": summary["levels"], "plans": summary["plans"],
                  "responder_route": summary["responder_route"],
                  "goal_cell": list(summary["goal_cell"])})
    return "".join(json.dumps(x, separators=(",", ":")) + "\n" for x in lines)


if __name__ == "__main__":
    from sim.demo_descent import run

    GOLDEN.write_text(record(run(floor="B1")))
    print(f"wrote {GOLDEN}")
