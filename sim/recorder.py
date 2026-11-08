"""Record a real sim run as JSONL (ref S1): every bus message plus the sim's own truth, for replay.

    SIM_RECORD=runs/live.jsonl uvicorn coord.hub:app      # record while the hub runs
    python -m sim.recorder summary runs/live.jsonl        # what is in a recording
    python -m sim.recorder slim runs/live.jsonl out.jsonl  # smaller copy to commit or serve

One JSON object per line, in the order things happened:
    {"t": <sim seconds>, "wall": <seconds since the recording started>, "topic": "...", "data": {...}}
- every topic in the contract (coord/messages.py TOPICS: map/cells, map/casualties, permit/route,
  gemini/receipt, route/*, world/change, ...) exactly as delivered on the bus;
- `sim/truth` after every world tick (10 Hz of sim time): what the sim knows that no sensor reports: the Scout and Responder poses
  in 3D (`pos` [x, y, z] of the robot's ground point, `yaw`), the Scout's sensor origin, the Responder's
  state, the true casualty positions, and whether the ground is shaking;
- a first `record/meta` line: scene, start time, topics recorded.
Camera frames and depth points are dropped from sensors/scout (large); SIM_RECORD_FULL=1 keeps them.
Lines are flushed as written, so a crash still leaves a usable file. The format is the {t, topic,
data} one the integration runner (#52) writes, so a replay can read either.
"""

import argparse
import collections
import json
import os
import pathlib
import time

HEAVY = ("camera", "points", "points_from")       # dropped from sensors/scout unless SIM_RECORD_FULL=1

FALLBACK_TOPICS = (
    "scene/loaded", "sensors/scout", "map/cells", "map/casualties", "map/hazards", "scout/goto",
    "route/proposed", "route/verified", "gate/decision", "gate/request", "gate/answer", "responder/action",
    "responder/pose", "operator/command", "world/change", "world/debris", "log/decision", "permit/route",
    "status/link", "status/budget", "status/gemini", "gemini/receipt", "say", "casualty/reply",
    "casualty/contact", "report/handover",
)


def contract_topics():
    try:
        from coord.messages import TOPICS
    except ImportError:
        return FALLBACK_TOPICS
    return tuple(TOPICS)


def _r(v, n=3):
    return [round(float(x), n) for x in v]


def truth(world):
    """The sim's ground truth right now (a `sim/truth` record's data)."""
    out = {
        "scene": getattr(world, "scene", None),
        "shaking": bool(world.shaking),
        "scout": {"pos": _r(world.pos), "yaw": round(float(world.yaw), 3),
                  "sensor": _r(world.sensor_origin) if hasattr(world, "sensor_origin") else _r(world.pos),
                  "state": world.state},
        "casualties": {name: _r(world.d.geom_xpos[g]) for name, g, _v in world.casualties},
    }
    r = getattr(world, "responder", None)
    if r is not None:
        out["responder"] = {"pos": _r(r.pos), "yaw": round(float(r.yaw), 3), "state": r.state,
                            "route": r.route}
    return out


class Recorder:
    def __init__(self, path, world, full=False):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("w", encoding="utf-8")
        self.world = world
        self.full = full
        self.started = time.monotonic()
        self.lines = 0

    def write(self, topic, data):
        line = {"t": round(float(self.world.t), 3), "wall": round(time.monotonic() - self.started, 3),
                "topic": topic, "data": data}
        self.file.write(json.dumps(line, separators=(",", ":"), default=str) + "\n")
        self.file.flush()
        self.lines += 1

    def on(self, topic):
        def record(data):
            if topic == "sensors/scout" and not self.full and isinstance(data, dict):
                data = {k: v for k, v in data.items() if k not in HEAVY}
            self.write(topic, data)
        return record

    def follow(self, world):
        """Write sim/truth after every world tick: wraps world.tick, so it is exact in sim time however
        busy the event loop is (a timer of its own fell to 4 Hz on a loaded hub)."""
        tick = world.tick

        def tick_and_record(dt=0.1):
            events = tick(dt)
            self.write("sim/truth", truth(world))
            return events

        world.tick = tick_and_record

    def close(self):
        if not self.file.closed:
            self.file.close()


def attach(world, bus, path=None):
    """Record this run if SIM_RECORD (or `path`) names a file. Returns the Recorder or None."""
    path = path or os.environ.get("SIM_RECORD")
    if not path:
        return None
    rec = Recorder(path, world, full=os.environ.get("SIM_RECORD_FULL") == "1")
    topics = contract_topics()
    rec.write("record/meta", {"scene": getattr(world, "scene", None), "topics": list(topics),
                              "started": time.strftime("%Y-%m-%dT%H:%M:%S")})
    for topic in topics:
        bus.subscribe(topic, rec.on(topic))
    rec.follow(world)
    return rec


def summary(path):
    """{topic: count}, the sim-time span and the truth rate of a recording."""
    counts, first, last = collections.Counter(), None, None
    with open(path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            counts[rec["topic"]] += 1
            first = rec["t"] if first is None else first
            last = rec["t"]
    span = (last or 0) - (first or 0)
    return {"topics": dict(counts), "t0": first, "t1": last,
            "truth_hz": round(counts["sim/truth"] / span, 1) if span else None}


# What `slim` keeps: every story message as recorded; the 10 Hz streams thinned; bulky arrays dropped.
SLIM_EVERY = {"sensors/scout": 2, "responder/pose": 2, "sim/truth": 5}   # keep 1 in N (5, 5 and 2 Hz)
SLIM_DROP_TOPICS = ("status/gemini", "map/points")                    # periodic status; depth clouds
SLIM_SENSOR_KEYS = ("t", "pose", "motion", "acoustic")                # the scout frame minus LiDAR/thermal


def slim(src, dst):
    """Write a smaller copy of a recording for committing or serving: story messages unchanged and in
    order; sensors/scout keeps pose, motion and acoustic; 10 Hz streams thinned; status/gemini and
    map/points dropped; a map/cells message identical to the one before it dropped (replaying it is a
    no-op whether a viewer merges or replaces). The record/meta line says what was dropped. Returns (lines in, lines out)."""
    seen, n_in, n_out, last_cells = collections.Counter(), 0, 0, None
    with open(src, encoding="utf-8") as f, open(dst, "w", encoding="utf-8", newline="\n") as out:
        for line in f:
            n_in += 1
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            topic = rec.get("topic")
            if topic in SLIM_DROP_TOPICS:
                continue
            if topic in SLIM_EVERY:
                seen[topic] += 1
                if (seen[topic] - 1) % SLIM_EVERY[topic]:
                    continue
            if topic == "map/cells":
                cells = json.dumps(rec.get("data", {}).get("cells"), separators=(",", ":"))
                if cells == last_cells:
                    continue                  # same map as the message before: a no-op to replay
                last_cells = cells
            if topic == "sensors/scout" and isinstance(rec.get("data"), dict):
                rec["data"] = {k: v for k, v in rec["data"].items() if k in SLIM_SENSOR_KEYS}
            if topic == "record/meta" and isinstance(rec.get("data"), dict):
                rec["data"]["slimmed"] = {"every": SLIM_EVERY, "dropped_topics": list(SLIM_DROP_TOPICS),
                                          "sensors_scout_keys": list(SLIM_SENSOR_KEYS)}
            rec.pop("wall", None)                                   # wall clock says nothing about the run
            out.write(json.dumps(rec, separators=(",", ":")) + "\n")
            n_out += 1
    return n_in, n_out


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary", help="topics, counts and time span of a recording")
    s.add_argument("path")
    sl = sub.add_parser("slim", help="a smaller copy for committing or serving (see slim())")
    sl.add_argument("src")
    sl.add_argument("dst")
    a = p.parse_args()
    if a.cmd == "slim":
        n_in, n_out = slim(a.src, a.dst)
        print(f"{n_in} lines -> {n_out} lines in {a.dst}")
        return
    print(json.dumps(summary(a.path), indent=2))


if __name__ == "__main__":
    main()
