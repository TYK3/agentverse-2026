"""INJECT-FUZZ: POST /inject answers every body with a clean 2xx/4xx and only valid requests reach the world.

Drives sim/inject.py's real route (loaded by path, so no MuJoCo is needed) on a recording stand-in world,
and the hub's own no-sim stand-in route, with a fixed corpus of malformed bodies plus a seeded random one.
The invariants, for every request:

- the status is 200, 400 or 409 on the sim route (400 or 503 on the hub's stand-in): never a 5xx or a
  dropped connection, and the body is a JSON object;
- the world is called only for a valid request: kind "aftershock", or kind "block_added" with pos a list
  of three finite real numbers (not booleans) of sane size. A NaN, an Infinity or a huge coordinate in
  MuJoCo's qpos makes MuJoCo flag the simulation unstable and RESET the whole world (checked with the
  backup scene: "Nan, Inf or huge value in QPOS"), so one bad inject would silently undo the rescue;
- every valid request does reach the world;
- the route still works after the fuzz.
"""

import importlib.util
import json
import math
import pathlib
import random

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from coord import hub

ROOT = pathlib.Path(__file__).resolve().parents[2]
SEED = 31
RANDOM_CASES = 400
SANE_M = 3.0            # valid positions the fuzz sends lie within +-3 m: inside every scene
HUGE_M = 1e6            # positions beyond this (and NaN / Infinity) must never reach the world

MALFORMED = {
    "empty": b"",
    "not_json": b"not json",
    "truncated": b'{"kind":',
    "trailing_comma": b'{"kind":"aftershock",}',
    "non_utf8": b'\xff\xfe{"kind":"aftershock"}',
    "nul": b'{"kind":"aftershock\x00"}',
    "deep_array": b"[" * 100_000 + b"]" * 100_000,
    "deep_in_kind": b'{"kind":' + b"[" * 100_000 + b"]" * 100_000 + b"}",
    "deep_in_pos": b'{"kind":"block_added","pos":' + b"[" * 100_000 + b"]" * 100_000 + b"}",
    "huge_int": b'{"kind":"block_added","pos":[' + b"9" * 5000 + b",0,0]}",
    "null": b"null",
    "string": b'"aftershock"',
    "number": b"1",
    "list": b'[{"kind":"aftershock"}]',
    "kind_list": b'{"kind":["aftershock"]}',
    "kind_object": b'{"kind":{"kind":"aftershock"}}',
    "kind_case": b'{"kind":"Aftershock"}',
    "kind_space": b'{"kind":"aftershock "}',
    "pos_missing": b'{"kind":"block_added"}',
    "pos_null": b'{"kind":"block_added","pos":null}',
    "pos_short": b'{"kind":"block_added","pos":[0.6,0.25]}',
    "pos_long": b'{"kind":"block_added","pos":[0.6,0.25,0.1,0]}',
    "pos_strings": b'{"kind":"block_added","pos":["0.6","0.25","0.1"]}',
    "pos_object": b'{"kind":"block_added","pos":{"x":0.6,"y":0.25,"z":0.1}}',
    "pos_nested": b'{"kind":"block_added","pos":[[0.6],[0.25],[0.1]]}',
    "pos_nan": b'{"kind":"block_added","pos":[NaN,0.25,0.1]}',
    "pos_inf": b'{"kind":"block_added","pos":[0.6,Infinity,0.1]}',
    "pos_neg_inf": b'{"kind":"block_added","pos":[0.6,0.25,-Infinity]}',
    "pos_huge": b'{"kind":"block_added","pos":[1e308,0.25,0.1]}',
    "pos_overflow": b'{"kind":"block_added","pos":[1e400,0.25,0.1]}',
    "pos_bools": b'{"kind":"block_added","pos":[true,false,true]}',
    "duplicate_kind": b'{"kind":"aftershock","kind":"nope"}',
}


def _sim_inject():
    """sim/inject.py by path: importing the sim package would need MuJoCo."""
    spec = importlib.util.spec_from_file_location("inject_under_fuzz", ROOT / "sim" / "inject.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RecordingWorld:
    """sim/inject.py's two World calls, recorded; always has a spare block and never refuses a shake."""

    def __init__(self):
        self.calls = []

    def add_block(self, pos):
        self.calls.append(("block_added", pos))
        return "spare0"

    def trigger_aftershock(self):
        self.calls.append(("aftershock", None))
        return True


def _real_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def expected(raw):
    """What a request must do: ("aftershock" | "block_added", pos) if it is valid, "reject" if it must
    not reach the world, or None for a sane-but-unusual pos (finite, between SANE_M and HUGE_M) that the
    handler may accept or refuse."""
    try:
        body = json.loads(raw)
    except (ValueError, RecursionError):
        return "reject"
    if not isinstance(body, dict):
        return "reject"
    kind = body.get("kind")
    if kind == "aftershock":
        return ("aftershock", None)
    if kind != "block_added":
        return "reject"
    pos = body.get("pos")
    if not (isinstance(pos, list) and len(pos) == 3 and all(_real_number(v) for v in pos)):
        return "reject"
    if any(abs(v) > HUGE_M for v in pos):
        return "reject"
    if all(abs(v) <= SANE_M for v in pos):
        return ("block_added", pos)
    return None


# ---------------------------------------------------------------- the seeded random corpus

def _value(rng, depth=0):
    kinds = ["int", "float", "special", "bool", "null", "str"] + (["list", "dict"] if depth < 3 else [])
    k = rng.choice(kinds)
    if k == "int":
        return rng.choice([0, 1, -1, 2**31, -(2**63), 10**30])
    if k == "float":
        return rng.uniform(-SANE_M, SANE_M) if rng.random() < 0.7 else rng.choice([1e7, -1e12, 1e308, 5e-324])
    if k == "special":
        return rng.choice([math.nan, math.inf, -math.inf])
    if k == "bool":
        return rng.random() < 0.5
    if k == "null":
        return None
    if k == "str":
        return rng.choice(["", "aftershock", "block_added", "x" * 1000, "é中\U0001f600", "\\u0000"])
    if k == "list":
        return [_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {rng.choice(["kind", "pos", "t", "id", ""]): _value(rng, depth + 1) for _ in range(rng.randint(0, 3))}


def _random_body(rng):
    roll = rng.random()
    if roll < 0.1:
        return bytes(rng.randrange(256) for _ in range(rng.randint(0, 64)))     # raw bytes
    body = {}
    if rng.random() < 0.9:
        body["kind"] = rng.choice(["aftershock", "block_added", "block_added", "", "quake", None, 1, ["aftershock"]])
    if rng.random() < 0.8:
        r = rng.random()
        if r < 0.4:
            body["pos"] = [rng.uniform(-SANE_M, SANE_M) for _ in range(3)]             # valid
        elif r < 0.8:
            body["pos"] = [_value(rng, 3) for _ in range(rng.choice([2, 3, 3, 3, 4]))]  # odd coordinates
        else:
            body["pos"] = _value(rng)
    for _ in range(rng.randint(0, 2)):
        body[rng.choice(["t", "extra", "pos2"])] = _value(rng)
    if roll < 0.15:
        body = [body]
    return json.dumps(body, allow_nan=True).encode()


def corpus():
    rng = random.Random(SEED)
    cases = list(MALFORMED.items())
    cases += [(f"random{i}", _random_body(rng)) for i in range(RANDOM_CASES)]
    cases += [(f"valid_block{i}", json.dumps({"kind": "block_added",
                                               "pos": [rng.uniform(-SANE_M, SANE_M) for _ in range(3)]}).encode())
              for i in range(20)]
    cases += [("valid_aftershock", b'{"kind":"aftershock"}'), ("valid_int_pos", b'{"kind":"block_added","pos":[1,0,0]}')]
    return cases


def test_the_corpus_covers_every_outcome():
    outcomes = [expected(raw) for _, raw in corpus()]
    assert sum(o == "reject" for o in outcomes) > 200
    assert sum(isinstance(o, tuple) and o[0] == "block_added" for o in outcomes) > 30
    assert sum(isinstance(o, tuple) and o[0] == "aftershock" for o in outcomes) > 10


# ---------------------------------------------------------------- the routes

@pytest.fixture
def hub_app(monkeypatch):
    """The hub app with no lanes, no Gemini task and a fresh bus; its routes restored after."""
    monkeypatch.setattr(hub, "bus", hub.Bus())
    monkeypatch.setattr(hub, "LANES", ())
    original = hub.importlib.import_module

    def imports(name):
        if name == "coord.gem":
            raise ModuleNotFoundError(name=name)
        return original(name)

    monkeypatch.setattr(hub.importlib, "import_module", imports)
    routes = list(hub.app.router.routes)
    yield hub.app
    hub.app.router.routes[:] = routes


def _post(client, raw):
    return client.post("/inject", content=raw, headers={"content-type": "application/json"})


def _json_object(response):
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def test_fuzzed_bodies_on_the_sims_route_never_5xx_and_only_valid_ones_reach_the_world(hub_app):
    world = RecordingWorld()
    assert _sim_inject().install(world, hub.bus)
    failures = []
    with TestClient(hub_app, raise_server_exceptions=False) as client:
        for name, raw in corpus():
            want = expected(raw)
            before = len(world.calls)
            r = _post(client, raw)
            got = world.calls[before:]
            body = _json_object(r)
            if r.status_code not in (200, 400, 409) or body is None:
                failures.append(f"{name}: {r.status_code} {r.text[:60]!r}")
            elif want == "reject" and (got or r.status_code == 200):
                failures.append(f"{name}: invalid body reached the world as {got!r:.60} ({r.status_code})")
            elif isinstance(want, tuple) and (r.status_code != 200 or got != [want] or body.get("ok") is not True):
                failures.append(f"{name}: valid body got {r.status_code} {body}, world saw {got!r:.60}")
            elif r.status_code == 400 and not isinstance(body.get("error"), str):
                failures.append(f"{name}: 400 without an error message: {body}")
        after = _post(client, b'{"kind":"aftershock"}')
    assert not failures, f"{len(failures)} of {len(corpus())} bodies broke an invariant:\n" + "\n".join(failures)
    assert after.status_code == 200 and world.calls[-1] == ("aftershock", None)
    assert not hub.bus.history                        # the route never publishes: world/change is the sim's


def test_fuzzed_bodies_on_the_hubs_no_sim_route_answer_400_or_503(hub_app):
    """Without a live sim the hub's own stand-in answers: 503 for a valid kind, 400 for anything else."""
    failures = []
    with TestClient(hub_app, raise_server_exceptions=False) as client:
        for name, raw in corpus():
            r = _post(client, raw)
            body = _json_object(r)
            try:
                parsed = json.loads(raw)
            except (ValueError, RecursionError):
                parsed = None
            valid_kind = isinstance(parsed, dict) and parsed.get("kind") in hub.INJECT_KINDS
            want = 503 if valid_kind else 400
            if r.status_code != want or body is None or not isinstance(body.get("error"), str):
                failures.append(f"{name}: want {want}, got {r.status_code} {r.text[:60]!r}")
    assert not failures, f"{len(failures)} bodies:\n" + "\n".join(failures)
    assert not hub.bus.history
