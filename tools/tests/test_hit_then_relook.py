"""HIT-THEN-RELOOK: every hit in a real B2 run log is followed by a relook before the Scout moves on.

The log is tools/run_b2.py, seed 0, GEMINI_MODE=off, live sim (LevelWorld). Hits and relooks
are the record kinds and fields below, read from that runner, sim/world.py, sim/levels.py,
perception/levels.py, and coord/CONTRACT.md.
"""

import json

import pytest

from tools.run_b2 import STOP_WINDOW, run

# A hit is a collision, contact, bump, or refused step.
# pose.state "blocked" is that event on this log. sim.world.World._free_ahead sets it when a
# ray meets geometry inside CLEARANCE (a collision, contact, or bump). sim.levels.LevelWorld._drive
# sets it when the floor check refuses the step (a drop, a kerb, or the wrong level). CONTRACT
# responder/pose uses the same state, "blocked".
# kind "mapped" with source "refused" is the refused step stored by perception.levels.GridLevels
# (_blocked and refuse write source "refused"). run_b2 copies that onto mapped.sources. Seed 0
# record 435 is kind "mapped" with sources ["lidar", "refused"]: the refused source is the hit.
# A record whose kind is collision, contact, bump, or refused would be the same event.
HIT_POSE_STATE = "blocked"
HIT_KINDS = frozenset({"collision", "contact", "bump", "refused"})
HIT_SOURCES = frozenset({"collision", "contact", "bump", "refused"})

# A relook is a fresh scan or a mapped update, or a relook / recheck record.
# kind "mapped" is the runner's mapped update (the slab measured into the map). It counts only
# when its sources are a scan, such as "lidar", and not a hit source. Record 435 includes
# "refused", so that record is the hit, not the relook after it.
# kind "relook" or "recheck", and why / reason / status / detail / outcome text naming a re-look,
# recheck, or fresh scan: CONTRACT gate/decision outcome "relook", permit/route evidence kind
# "fresh_scan", and scout/goto reason "re-look at cell ...". This runner's plan.why is only
# "explore", "probe", or "route", and a plan is the robot moving on, not the relook before it.
RELOOK_KINDS = frozenset({"relook", "recheck"})
RELOOK_TEXT = ("relook", "re-look", "recheck", "re-check", "fresh scan", "fresh_scan", "re-scan", "rescan")
TEXT_FIELDS = ("why", "reason", "status", "detail", "outcome")


def _sources(row):
    found = []
    sources = row.get("sources")
    if isinstance(sources, list):
        found.extend(str(item) for item in sources)
    source = row.get("source")
    if isinstance(source, str):
        found.append(source)
    return found


def hit_name(row):
    """Short name of the hit field on this record, or None."""
    if row.get("kind") == "pose" and row.get("state") == HIT_POSE_STATE:
        return "pose state blocked"
    if row.get("kind") in HIT_KINDS:
        return f"kind {row['kind']}"
    matched = HIT_SOURCES.intersection(_sources(row))
    if row.get("kind") == "mapped" and matched:
        return "mapped source " + ",".join(sorted(matched))
    return None


def relook_name(row):
    """Short name of the relook field on this record, or None. A hit record is not its own relook."""
    if hit_name(row):
        return None
    if row.get("kind") == "mapped":
        return "mapped update"
    if row.get("kind") in RELOOK_KINDS:
        return f"kind {row['kind']}"
    text = " ".join(str(row.get(key) or "") for key in TEXT_FIELDS)
    folded = text.lower().replace("-", "").replace("_", "")
    for word in RELOOK_TEXT:
        if word.lower().replace("-", "").replace("_", "") in folded:
            return f"text {word}"
    return None


def moves_on(row):
    """The next moving pose, or the next plan: the robot has moved on."""
    if row.get("kind") == "plan":
        return True
    return row.get("kind") == "pose" and row.get("state") == "moving"


def relook_before_moving_on(records, index):
    """Index of a relook after this hit, before the next moving pose or plan, inside STOP_WINDOW.

    STOP_WINDOW (tools.run_b2) is the runner's window, in sim seconds.
    """
    start = records[index]["t"]
    for later in range(index + 1, len(records)):
        row = records[later]
        if row["t"] - start > STOP_WINDOW:
            return None
        if moves_on(row):
            return None
        if relook_name(row):
            return later
    return None


@pytest.mark.slow
def test_every_hit_has_a_relook_before_the_scout_moves_on(tmp_path, monkeypatch):
    pytest.importorskip("mujoco")
    monkeypatch.setenv("GEMINI_MODE", "off")
    _verdict, path = run(seed=0, out_dir=tmp_path)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    hits = [(i, hit_name(row), row["t"]) for i, row in enumerate(records) if hit_name(row)]
    assert hits, "no hit in the run"
    missing = []
    for index, name, at in hits:
        found = relook_before_moving_on(records, index)
        if found is None:
            missing.append(f"record {index} ({name}, t={at})")
    assert not missing, (
        "no relook after the hit and before the next moving pose or plan "
        f"within tools.run_b2.STOP_WINDOW ({STOP_WINDOW} s): " + "; ".join(missing)
    )
