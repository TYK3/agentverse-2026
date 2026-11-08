"""Replay labelled Y6 development fixtures; no real patients, sensors or model calls."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from planner.report import REPORTS, ReportCollector
from planner.report_run import PrintBus


async def run(output_dir):
    fixture = json.loads((Path(__file__).parent / "fixtures" / "paramedic.json").read_text(encoding="utf-8"))
    assert fixture["development_example"] is True
    print("DEVELOPMENT FIXTURE: synthetic casualties, replies and placement logs; not a live rescue.", file=sys.stderr)
    bus, now = PrintBus(), [0.0]
    collector = ReportCollector(bus, output_dir=output_dir, clock=lambda: now[0],
                                dialogue_summary=lambda cid: fixture["dialogue"].get(cid)).attach()
    for event in fixture["events"]:
        now[0] += 1
        await bus.publish(event["topic"], event["data"])
    result = await collector.generate()
    print(f"DEVELOPMENT FIXTURE report: {result['path']}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=REPORTS)
    asyncio.run(run(parser.parse_args().output_dir))
