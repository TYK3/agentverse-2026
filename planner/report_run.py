"""Replay DEVELOPMENT FIXTURES into the real template handover renderer."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from planner.report import REPORTS, ReportCollector


class PrintBus:
    def __init__(self):
        self.subs = {}

    def subscribe(self, topic, callback):
        self.subs.setdefault(topic, []).append(callback)

    async def publish(self, topic, data):
        for callback in self.subs.get(topic, []):
            result = callback(data)
            if asyncio.iscoroutine(result):
                await result
        if topic == "report/handover":
            print(json.dumps({"topic": topic, "data": data}))


async def run(output_dir):
    bus = PrintBus()
    now = [0.0]
    reporter = ReportCollector(bus, output_dir=output_dir, clock=lambda: now[0]).attach()
    path = Path(__file__).parent / "fixtures" / "handover.json"
    for envelope in json.loads(path.read_text(encoding="utf-8")):
        now[0] += 1
        await bus.publish(envelope["topic"], envelope["data"])
    result = await reporter.generate()
    print(f"DEVELOPMENT FIXTURES; handover written to {result['path']}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=REPORTS)
    asyncio.run(run(parser.parse_args().output_dir))
