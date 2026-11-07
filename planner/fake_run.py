"""Development fixture runner: real local A*, no sim or Gemini claims."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from planner import start


class FixtureBus:
    def __init__(self):
        self.subscribers = {}

    def subscribe(self, topic, callback):
        self.subscribers.setdefault(topic, []).append(callback)

    async def publish(self, topic, data):
        for callback in self.subscribers.get(topic, []):
            callback(data)
        if topic == "route/proposed":
            print(json.dumps({"topic": topic, "data": data}))


async def run(args):
    bus = FixtureBus()
    planner = await start(bus)
    await bus.publish("map/cells", json.loads(args.map.read_text(encoding="utf-8")))
    await bus.publish("map/hazards", json.loads(args.hazards.read_text(encoding="utf-8")))
    result = await planner.propose(args.start, args.goal, goal_text=args.goal_text)
    if result["status"] != "ok":
        print(json.dumps(result))
        return 1
    return 0


def main():
    fixtures = Path(__file__).parent / "fixtures"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, default=fixtures / "map__cells.json")
    parser.add_argument("--hazards", type=Path, default=fixtures / "map__hazards.json")
    parser.add_argument("--start", type=int, nargs=3, default=[0, 2, 0])
    parser.add_argument("--goal", type=int, nargs=3, default=[6, 2, 0])
    parser.add_argument("--goal-text", default="deliver water to c1")
    args = parser.parse_args()
    print(
        f"DEVELOPMENT FIXTURES: {args.map}; {args.hazards}. "
        "Local A* proposal; physics verification pending; no Gemini calls.",
        file=sys.stderr,
    )
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
