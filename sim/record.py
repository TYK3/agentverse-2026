"""Record the Scout sensor stream on the backup scene: the fake perception builds against.

    python -m sim.record --seconds 60

Runs in simulated time (faster than real time), drives the Scout along TOUR with scout/goto
commands, and writes one {"topic":"sensors/scout","data":{...}} line per tick at 10 Hz.
Camera frames are left out. Default output: sim/recordings/scout_backup.jsonl.
"""

import argparse
import json
import pathlib

from sim.world import World

OUT = pathlib.Path(__file__).parent / "recordings" / "scout_backup.jsonl"

# In through the breach, room 1, the doorway, room 2, the partly blocked gap, room 3, and back.
TOUR = [
    ([-0.5, -0.3], "enter room 1 through the breach"),
    ([-0.3, 0.25], "line up with the doorway"),
    ([0.6, 0.25], "cross into room 2"),
    ([0.8, 0.73], "line up with the gap to room 3"),
    ([1.6, 0.73], "squeeze past rubble b11 into room 3"),
    ([1.9, 0.3], "look at room 3"),
    ([1.6, 0.73], "back to the gap"),
    ([0.8, 0.73], "back into room 2"),
    ([0.6, -0.2], "look along the leaning slab b10"),
    ([-0.3, 0.25], "back to the doorway"),
    ([-1.1, 0.8], "look at the north-west of room 1"),
]


def record(seconds=60.0, out=OUT, rate_hz=10, tour=TOUR):
    world = World(render=False)
    dt = 1.0 / rate_hz
    stops = list(tour)
    lines, states = [], []
    for _ in range(round(seconds * rate_hz)):
        if stops and world.state in ("idle", "arrived", "blocked"):
            target, reason = stops.pop(0)
            world.goto({"target": target + [0.075], "reason": reason})
        world.tick(dt)
        data = world.sensors_message(camera=False)
        states.append(data["motion"]["state"])
        lines.append(json.dumps({"topic": "sensors/scout", "data": data}, separators=(",", ":")))
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out, states


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--out", default=str(OUT))
    a = p.parse_args()
    out, states = record(a.seconds, a.out)
    print(f"wrote {len(states)} messages to {out}; blocked ticks: {states.count('blocked')}")


if __name__ == "__main__":
    main()
