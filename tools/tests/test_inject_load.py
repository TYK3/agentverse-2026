"""INJECT-LOAD-TEST: POST /inject survives 200 rapid calls over real TCP.

HUB-SOAK saw an httpx.ReadError on POST /inject after ~1000 cycles against a real Uvicorn hub with the
sim's own route (sim/inject.py) installed. These tests drive the same stack: Uvicorn on a real socket
(not the ASGI TestClient), one persistent HTTPX client (keep-alive, as the soak used), valid requests
alternating aftershock / block_added, and a /ws client that reconnects every few calls. Every call must
get a well-formed JSON answer with a 2xx/4xx status: no transport error, no reset, no 5xx.

- test_200_rapid_injects_*_synthetic_world: sim/inject.py's real route on a stand-in world, so it runs
  wherever FastAPI and Uvicorn are installed (the coord/tools CI job), without MuJoCo.
- test_200_rapid_injects_*_live_sim: the real sim lane on the hub (skipped without MuJoCo; runs in the
  full-test job and locally).
"""

import importlib.util
import json
import pathlib
import threading
import time

import pytest

pytest.importorskip("fastapi")
uvicorn = pytest.importorskip("uvicorn")
httpx = pytest.importorskip("httpx")
ws_client = pytest.importorskip("websockets.sync.client")

from coord import hub

ROOT = pathlib.Path(__file__).resolve().parents[2]
CALLS = 200
WS_EVERY = 10          # reconnect the /ws client every this many calls, as the soak's console did
SPARE = 3              # spare blocks in the stand-in world: later block_added calls get 409


def _inject_module():
    """sim/inject.py by path: importing the sim package would need MuJoCo."""
    spec = importlib.util.spec_from_file_location("inject_under_test", ROOT / "sim" / "inject.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class StandInWorld:
    """The two calls sim/inject.py makes on the World, with the World's answers (name / None, bool)."""

    def __init__(self):
        self.spare = [f"spare{i}" for i in range(SPARE)]
        self.shaking = False
        self.calls = []

    def add_block(self, pos):
        self.calls.append(("block_added", pos))
        return self.spare.pop(0) if self.spare else None

    def trigger_aftershock(self):
        # the real World refuses while a shake runs; alternate so both 200 and 409 come back
        self.calls.append(("aftershock", None))
        self.shaking = not self.shaking
        return self.shaking


class Hub:
    """coord.hub.app on Uvicorn, on a free 127.0.0.1 port, in a background thread."""

    def __init__(self):
        config = uvicorn.Config(hub.app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
        self.server = uvicorn.Server(config)
        self.server.install_signal_handlers = lambda: None     # not the main thread (older Uvicorn)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        end = time.monotonic() + 60
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > end:
                raise RuntimeError("uvicorn did not start")
            time.sleep(0.02)
        sock = self.server.servers[0].sockets[0]
        self.port = sock.getsockname()[1]
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=30)

    @property
    def http(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def ws(self):
        return f"ws://127.0.0.1:{self.port}/ws"


@pytest.fixture
def hub_lanes(monkeypatch):
    """A fresh bus and lane list on the hub, no Gemini status task; restores the hub's routes after."""
    monkeypatch.setattr(hub, "bus", hub.Bus())
    original = hub.importlib.import_module

    def imports(name):
        if name == "coord.gem":
            raise ModuleNotFoundError(name=name)
        return original(name)

    monkeypatch.setattr(hub.importlib, "import_module", imports)
    routes = list(hub.app.router.routes)
    yield lambda lanes: monkeypatch.setattr(hub, "LANES", lanes)
    hub.app.router.routes[:] = routes


def _body(i):
    if i % 2:
        return {"kind": "block_added", "pos": [-0.9 + 0.01 * (i % 7), 0.25, 0.3]}
    return {"kind": "aftershock"}


def hammer(server, calls=CALLS):
    """POST `calls` valid injects on one keep-alive client while a /ws client reconnects every WS_EVERY
    calls. Returns the (status, json) answers in order; raises on any transport error."""
    answers = []
    with httpx.Client(base_url=server.http, timeout=10.0) as client:
        for start in range(0, calls, WS_EVERY):
            with ws_client.connect(server.ws, open_timeout=10):
                for i in range(start, min(start + WS_EVERY, calls)):
                    r = client.post("/inject", json=_body(i))
                    answers.append((r.status_code, json.loads(r.content)))
    return answers


def _check(answers):
    assert len(answers) == CALLS
    statuses = [s for s, _ in answers]
    assert all(s in (200, 409) for s in statuses), [a for a in answers if a[0] not in (200, 409)][:5]
    for status, body in answers:
        assert isinstance(body, dict)
        assert body.get("ok") is True if status == 200 else isinstance(body.get("error"), str)


def test_200_rapid_injects_over_tcp_on_the_sims_route_synthetic_world(hub_lanes):
    hub_lanes(())                                    # no lanes: the route below is the sim's own
    world = StandInWorld()
    assert _inject_module().install(world, hub.bus)
    with Hub() as server:
        answers = hammer(server)
        # the server is still healthy afterwards: a malformed body is a 400, not a dropped connection
        with httpx.Client(base_url=server.http, timeout=10.0) as client:
            bad = client.post("/inject", json={"kind": "nope"})
    _check(answers)
    assert len(world.calls) == CALLS                  # every request reached the world, none was lost
    blocks = [b for (s, b), i in zip(answers, range(CALLS), strict=True) if i % 2 and s == 200]
    assert [b["block"] for b in blocks] == [f"spare{i}" for i in range(SPARE)]
    assert sum(1 for s, _ in answers[0::2] if s == 200) == CALLS // 4     # aftershock: every other one runs
    assert bad.status_code == 400


def test_200_rapid_injects_over_tcp_without_a_sim_answer_503(hub_lanes):
    """The hub's own stand-in route (no sim lane) under the same load: 503 every time, never a reset."""
    hub_lanes(())
    with Hub() as server, httpx.Client(base_url=server.http, timeout=10.0) as client:
        answers = [(r.status_code, r.json()) for r in (client.post("/inject", json=_body(i)) for i in range(CALLS))]
    assert {s for s, _ in answers} == {503}
    assert all(b == {"error": "no live sim on this hub"} for _, b in answers)


def test_200_rapid_injects_over_tcp_on_the_live_sim(hub_lanes, monkeypatch):
    pytest.importorskip("mujoco")
    monkeypatch.delenv("SIM_SCENE", raising=False)   # the backup scene, as the demo uses
    hub_lanes(("sim",))
    with Hub() as server:
        answers = hammer(server)
        with ws_client.connect(server.ws, open_timeout=10) as ws:   # the sim loop is still publishing
            end, topics = time.monotonic() + 20, set()
            while "world/change" not in topics and time.monotonic() < end:
                topics.add(json.loads(ws.recv(timeout=end - time.monotonic()))["topic"])
    _check(answers)
    added = [b for (s, b), i in zip(answers, range(CALLS), strict=True) if i % 2 and s == 200]
    assert len(added) == 1                           # the backup scene has one spare block
    assert any(s == 200 for s, _ in answers[0::2])   # at least the first aftershock ran
    assert "world/change" in topics
