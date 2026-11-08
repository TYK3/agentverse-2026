"""RUN-GET: GET /run on the hub reports the chained rescue run's state, and never starts one.

Shape approved on the board (04:34 London, 2026-11-08):
    {"state": "idle"|"running"|"done"|"failed", "floor": "B1"|"B2"|"B3"|null, "t": sim seconds,
     "log": "runs/<name>.jsonl"|null, "verdict": {"passed": [...], "failed": [...]}|null}
always HTTP 200, and a GET never starts a run (RUN-ROUTE's POST /run/rescue does that).

These run against coord.hub.app through the ASGI TestClient, with no lanes started. They are red until
RUN-ROUTE adds the route. `check_run_shape` is shared so RUN-ROUTE / RUN-PROGRESS tests can check the
running and finished states with the same rules.
"""

import re
import subprocess

import pytest
from fastapi.testclient import TestClient

from coord import hub
from coord.tests.test_inject_cors import CONSOLE, clean_bus  # noqa: F401  (fixture)

STATES = {"idle", "running", "done", "failed"}
FLOORS = {"B1", "B2", "B3"}
LOG = re.compile(r"^runs/[A-Za-z0-9_.-]+\.jsonl$")


def check_run_shape(body):
    """Every rule of the approved GET /run shape; returns the body so calls can chain."""
    assert isinstance(body, dict), body
    assert set(body) == {"state", "floor", "t", "log", "verdict"}, sorted(body)
    state, floor, t, log, verdict = (body[k] for k in ("state", "floor", "t", "log", "verdict"))
    assert state in STATES, state
    assert floor is None or floor in FLOORS, floor
    assert isinstance(t, (int, float)) and not isinstance(t, bool) and t >= 0, t
    assert log is None or (isinstance(log, str) and LOG.match(log)), log
    if verdict is not None:
        assert isinstance(verdict, dict) and set(verdict) == {"passed", "failed"}, verdict
        for names in verdict.values():
            assert isinstance(names, list) and all(isinstance(n, str) and n for n in names), verdict
        assert not set(verdict["passed"]) & set(verdict["failed"]), verdict
    if state == "idle":
        assert floor is None and log is None and verdict is None, body
    if state == "running":
        assert verdict is None and log is not None, body
    if state in ("done", "failed"):
        assert verdict is not None and log is not None, body
    if state == "done":
        assert verdict["failed"] == [], body
    return body


@pytest.fixture
def client(clean_bus, monkeypatch, tmp_path):  # noqa: F811
    """The hub app with no lanes; any attempt to start a process or a run fails the test."""
    monkeypatch.chdir(tmp_path)

    def no_process(*args, **kwargs):
        pytest.fail(f"GET /run started a process: {args[:1]}")

    monkeypatch.setattr(subprocess, "Popen", no_process)
    monkeypatch.setattr(subprocess, "run", no_process)
    monkeypatch.setattr(hub.asyncio, "create_subprocess_exec", no_process)
    return TestClient(hub.app)


def test_a_fresh_hub_reports_idle_with_the_approved_shape(client):
    reply = client.get("/run")
    assert reply.status_code == 200, (reply.status_code, reply.text[:200])
    assert reply.headers["content-type"].startswith("application/json")
    body = check_run_shape(reply.json())
    assert body["state"] == "idle"


def test_repeated_gets_never_start_a_run(client, tmp_path):
    states = [check_run_shape(client.get("/run").json())["state"] for _ in range(10)]
    assert states == ["idle"] * 10
    assert not list(tmp_path.rglob("*.jsonl")), "a GET wrote a run log"


def test_query_strings_still_answer_200_and_change_nothing(client):
    for query in ("?floor=B3", "?start=1", "?seed=0&floor=B1", "?state=running"):
        reply = client.get("/run" + query)
        assert reply.status_code == 200, (query, reply.status_code)
        assert check_run_shape(reply.json())["state"] == "idle", query


def test_other_methods_on_run_do_not_start_a_run(client):
    for method in ("post", "put", "delete"):
        reply = getattr(client, method)("/run")
        assert reply.status_code == 405, (method, reply.status_code)
    assert check_run_shape(client.get("/run").json())["state"] == "idle"


def test_the_console_origin_may_read_run_state(client):
    reply = client.get("/run", headers={"Origin": CONSOLE})
    assert reply.status_code == 200
    assert reply.headers.get("access-control-allow-origin") == CONSOLE


@pytest.mark.parametrize("body", [
    {"state": "idle", "floor": None, "t": 0, "log": None, "verdict": None},
    {"state": "running", "floor": "B2", "t": 41.5, "log": "runs/b2-0.jsonl", "verdict": None},
    {"state": "done", "floor": "B3", "t": 225.8, "log": "runs/chain-0.jsonl",
     "verdict": {"passed": ["no teleport"], "failed": []}},
    {"state": "failed", "floor": "B1", "t": 88.7, "log": "runs/b1-0.jsonl",
     "verdict": {"passed": [], "failed": ["Scout stopped short of the slab"]}},
])
def test_the_shape_checker_accepts_each_state(body):
    check_run_shape(body)


@pytest.mark.parametrize("body", [
    {"state": "idle", "floor": None, "t": 0, "log": None},                                   # missing key
    {"state": "starting", "floor": None, "t": 0, "log": None, "verdict": None},              # unknown state
    {"state": "idle", "floor": "B2", "t": 0, "log": None, "verdict": None},                 # idle with a floor
    {"state": "running", "floor": "B4", "t": 1, "log": "runs/x.jsonl", "verdict": None},    # unknown floor
    {"state": "running", "floor": "B1", "t": -1, "log": "runs/x.jsonl", "verdict": None},   # negative t
    {"state": "running", "floor": "B1", "t": True, "log": "runs/x.jsonl", "verdict": None},  # bool t
    {"state": "running", "floor": "B1", "t": 1, "log": "/etc/x.jsonl", "verdict": None},    # log outside runs/
    {"state": "done", "floor": "B1", "t": 1, "log": "runs/x.jsonl", "verdict": None},       # done, no verdict
    {"state": "done", "floor": "B1", "t": 1, "log": "runs/x.jsonl",
     "verdict": {"passed": [], "failed": ["x"]}},                                            # done but failed
])
def test_the_shape_checker_rejects_broken_bodies(body):
    with pytest.raises(AssertionError):
        check_run_shape(body)
