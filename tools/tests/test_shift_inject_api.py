"""SHIFT-INJECT-API-TEST: during a short B2 run the slab shift is posted to the hub, and the
run log shows shift, then stop, then recheck, in that order.

tools/run_b2.py with seed 0 decides when the slab is due. That moment is a real POST /inject of
the console's slab shift, {"kind": "block_added", "pos": [x, y, z]} (coord/CONTRACT.md). The sim's
inject handler places the spare block. This test does not place the block and does not write the
log. TestClient stays in-process and does not start the hub lifespan, so no lane runs and nothing
is opened on the network. GEMINI_MODE is off.
"""

import json

import pytest

pytest.importorskip("mujoco")
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from coord import hub
from sim import inject
from tools import run_b2

# tools/run_b2.py counts these pose states as the Scout having stopped short of the slab.
STOP_STATES = ("blocked", "idle", "arrived")


def _post_slab_shift(client, world, xy, floor_z, posted):
    """Hand the runner's drop to POST /inject. The handler places the block; this function does not."""
    assert inject.install(world, hub.bus) is True
    z = float(floor_z) + run_b2.SLAB_HALF[2] + 0.002
    body = {"kind": "block_added", "pos": [float(xy[0]), float(xy[1]), z]}
    response = client.post("/inject", json=body)
    block = world.m.body("x1").id
    posted.append({
        "status": response.status_code,
        "json": response.json(),
        "body": body,
        "xpos": [round(float(v), 4) for v in world.d.xpos[block]],
        "t": round(float(world.t), 2),
    })


def _markers(rows):
    """Indices of the shift, the stop pose after it, and the plan (recheck) after that stop.

    A missing marker is None. The three indices have to increase: shift, then stop, then recheck.
    """
    shift = next((i for i, row in enumerate(rows) if row.get("kind") == "shift"), None)
    stop = None
    if shift is not None:
        stop = next((i for i in range(shift + 1, len(rows))
                     if rows[i].get("kind") == "pose" and rows[i].get("state") in STOP_STATES), None)
    recheck = None
    if stop is not None:
        recheck = next((i for i in range(stop + 1, len(rows)) if rows[i].get("kind") == "plan"), None)
    return shift, stop, recheck


def _transcript(rows, start):
    lines = []
    for row in rows[start:]:
        if row.get("kind") not in ("shift", "pose", "plan", "mapped", "summary"):
            continue
        detail = row.get("state") or row.get("status") or ""
        extra = f" {detail}" if detail else ""
        if row.get("why"):
            extra += f" {row['why']}"
        if row.get("kind") == "mapped":
            extra = " " + ",".join(row.get("sources") or [])
        lines.append(f"  t={row.get('t')} {row.get('kind')}{extra}")
    return "\n".join(lines)


def test_b2_seed_0_posts_the_slab_shift_and_logs_shift_then_stop_then_recheck(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_MODE", "off")
    # inject.install rewrites this list in place; the original routes go back when the test ends.
    monkeypatch.setattr(hub.app.router, "routes", list(hub.app.router.routes))
    posted = []
    client = TestClient(hub.app)

    def drop_via_inject(world, xy, floor_z):
        _post_slab_shift(client, world, xy, floor_z, posted)

    monkeypatch.setattr(run_b2, "drop_slab", drop_via_inject)
    _verdict, path = run_b2.run(seed=0, out_dir=tmp_path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    shift, stop, recheck = _markers(rows)
    post = posted[0] if len(posted) == 1 else posted
    evidence = (
        f"POST /inject slab shift: {post}\n"
        f"markers shift={shift} stop={stop} recheck={recheck}\n"
        f"log {path.name} from the shift onward:\n{_transcript(rows, shift or 0)}"
    )
    assert len(posted) == 1 and posted[0]["status"] == 200 and posted[0]["json"].get("ok") is True, evidence
    assert shift is not None, evidence
    asked = posted[0]["body"]["pos"]
    assert rows[shift]["kind"] == "shift"
    assert rows[shift]["xy"] == [round(asked[0], 3), round(asked[1], 3)], evidence
    assert stop is not None and recheck is not None and shift < stop < recheck, evidence
