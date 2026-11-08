"""Check a recorded B1 rescue before using it as the console demo.

    python tools/check_demo.py runs/rescue-7.jsonl

The runner's own step results are the pass criterion. This command also checks
that the log is complete and contains the observed change, permit recovery,
delivery and report that the console needs. It never edits the recording.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys


def check(path: pathlib.Path, expected_steps: int = 16) -> list[str]:
    errors: list[str] = []
    records = []
    malformed = 0
    try:
        with path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    malformed += 1
                    if malformed <= 3:
                        errors.append(f"line {line_number}: invalid JSON: {exc.msg}")
                    continue
                if not isinstance(record, dict) or not isinstance(record.get("topic"), str) or "data" not in record:
                    malformed += 1
                    if malformed <= 3:
                        errors.append(f"line {line_number}: expected topic and data")
                    continue
                records.append(record)
    except OSError as exc:
        return [f"cannot read {path}: {exc}"]
    if malformed > 3:
        errors.append(f"{malformed - 3} more malformed lines")

    topics = [r["topic"] for r in records]
    steps = [r["data"] for r in records if r["topic"] == "_runner/step"]
    summaries = [r["data"] for r in records if r["topic"] == "_runner/summary"]
    if len(steps) != expected_steps:
        errors.append(f"expected {expected_steps} runner steps; found {len(steps)}")
    if any(not isinstance(s, dict) or s.get("ok") is not True for s in steps):
        failed = [str(s.get("step", "unknown")) if isinstance(s, dict) else "unknown"
                  for s in steps if not isinstance(s, dict) or s.get("ok") is not True]
        errors.append(f"runner steps failed: {', '.join(failed)}")
    if len(summaries) != 1 or topics[-1:] != ["_runner/summary"]:
        errors.append("expected one final _runner/summary")
    else:
        summary = summaries[0]
        if not isinstance(summary, dict) or summary.get("passed") != expected_steps or summary.get("failed") != []:
            errors.append("runner summary does not confirm all steps passed")
    if any("rejected" in r for r in records):
        errors.append("recording contains a rejected bus message")

    required = ("scene/loaded", "map/casualties", "world/change", "route/verified",
                "responder/action", "report/handover")
    for topic in required:
        if topic not in topics:
            errors.append(f"missing {topic}")
    def first_after(start: int, topic: str, predicate):
        return next((i for i in range(start + 1, len(records))
                     if records[i]["topic"] == topic and isinstance(records[i]["data"], dict)
                     and predicate(records[i]["data"])), None)

    change = first_after(-1, "world/change", lambda d: d.get("kind") in ("aftershock", "block_added"))
    revoke = first_after(change, "permit/route", lambda d: d.get("granted") is False) if change is not None else None
    regrant = first_after(revoke, "permit/route", lambda d: d.get("granted") is True) if revoke is not None else None
    delivery = first_after(regrant, "responder/action", lambda d: d.get("action") == "place_supply") if regrant is not None else None
    report = first_after(delivery, "report/handover", lambda d: True) if delivery is not None else None
    if None in (change, revoke, regrant, delivery, report):
        errors.append("missing ordered world change -> permit revoke -> regrant -> supply -> report")
    if not any(r["topic"] == "_runner/stage" and isinstance(r["data"], dict)
               and r["data"].get("stage") == "b1" and r["data"].get("reached") is True for r in records):
        errors.append("missing completed B1 stage")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("recording", type=pathlib.Path)
    args = parser.parse_args(argv)
    errors = check(args.recording)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS: 16/16 B1 rescue checks: {args.recording}")
    print(f"Replay: python tools/demo.py --replay {json.dumps(str(args.recording))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
