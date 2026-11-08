"""Record the Scout sensor stream on the backup scene: the fake perception builds against.

    python -m sim.record --seconds 60
    python -m sim.record --seconds 60 --scene tower      # -> sim/recordings/scout_tower.jsonl

Runs in simulated time (faster than real time), drives the Scout along TOUR with scout/goto
commands, and writes one {"t":sim seconds,"topic":"sensors/scout","data":{...}} line per tick at 10 Hz.
Camera frames are left out. Default output: sim/recordings/scout_backup.jsonl.
"""

import argparse
import json
import pathlib

from sim import scene
from sim.world import World

RECORDINGS = pathlib.Path(__file__).parent / "recordings"
OUT = RECORDINGS / "scout_backup.jsonl"

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


# The tower (ref Y1): in at the entrance, past c1, through the door into the collapsed east room along
# the voids (c3 under the pancake slab, c2 behind the lean-to closure), back out, and in at the breach to c4.
TOWER_TOUR = [
    ([-0.3, -1.0], "enter the west room"),
    ([-0.9, 0.2], "look at the west room (c1)"),
    ([-0.3, 0.8], "line up with the door"),
    ([0.65, 0.8], "through the door into the collapsed east room"),
    ([0.65, 0.0], "along the corridor by the lean-to"),
    ([1.2, -0.1], "between the pancake slab and the lean-to closure"),
    ([0.65, 0.0], "back to the corridor"),
    ([0.65, 0.8], "back to the door"),
    ([-0.3, 0.8], "back into the west room"),
    ([-0.3, -2.2], "out through the entrance"),
    ([1.58, -2.2], "along the outside to the breach"),
    ([1.58, -1.5], "into the breach, beside c4"),
]
TOURS = {"backup": TOUR, "tower": TOWER_TOUR}


def record(seconds=60.0, out=OUT, rate_hz=10, tour=TOUR, path=scene.BACKUP):
    world = World(path=path, render=False)
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
        lines.append(json.dumps({"t": data["t"], "topic": "sensors/scout", "data": data}, separators=(",", ":")))
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out, states


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--scene", default="backup", help="backup (default) or tower")
    p.add_argument("--out", default=None, help="default: sim/recordings/scout_<scene>.jsonl")
    a = p.parse_args()
    name, path = scene.resolve(a.scene)
    out = a.out or RECORDINGS / f"scout_{name}.jsonl"
    out, states = record(a.seconds, out, tour=TOURS.get(name, []), path=path)
    print(f"wrote {len(states)} messages to {out}; blocked ticks: {states.count('blocked')}")


if __name__ == "__main__":
    main()
