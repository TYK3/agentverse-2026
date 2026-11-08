"""RUN-ROUTE: the hub starts one chained rescue and forwards its log."""

import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from coord import hub
from tools import run_b2


@pytest.fixture
def isolated_bus(monkeypatch):
    target = hub.Bus()
    monkeypatch.setattr(hub, "bus", target)
    monkeypatch.setattr(hub, "LANES", ())
    original = hub.importlib.import_module

    def imports(name):
        if name == "coord.gem":
            raise ModuleNotFoundError(name=name)
        return original(name)

    monkeypatch.setattr(hub.importlib, "import_module", imports)
    return target


def fake_chain():
    def leg_records(path):
        return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]

    def chain(legs, seed):
        out = [{"t": 0.0, "kind": "meta", "seed": seed}]
        offset = 0.0
        for floor, records, verdict in legs:
            out.extend({**r, "kind": "leg_summary" if r["kind"] == "summary" else r["kind"],
                        "leg": floor, "leg_t": r["t"], "t": offset + r["t"]} for r in records)
            offset = out[-1]["t"]
            out.append({"t": offset, "kind": "leg", "floor": floor, "passed": len(verdict["passed"]),
                        "failed": len(verdict["failed"])})
        passed = [f"{floor}: {name}" for floor, _, verdict in legs for name in verdict["passed"]]
        failed = [f"{floor}: {name}" for floor, _, verdict in legs for name in verdict["failed"]]
        out.append({"t": offset, "kind": "summary", "passed": len(passed), "failed": failed})
        return out

    return SimpleNamespace(leg_records=leg_records, chain=chain, CASUALTY={"B1": "c1"})


def until_finished(client):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        status = client.get("/run").json()
        if status["state"] in {"done", "failed"}:
            return status
        time.sleep(0.01)
    raise AssertionError("run did not finish")


def test_post_starts_in_background_streams_log_and_rejects_overlap(isolated_bus, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "tools.run_chain", fake_chain())
    entered, release = threading.Event(), threading.Event()

    def run(seed, out_dir, floor, **_):
        entered.set()
        assert release.wait(2), "the route blocked the TestClient"
        path = Path(out_dir) / f"{floor.lower()}-{seed}.jsonl"
        path.write_text('\n'.join(json.dumps(r) for r in [
            {"t": 0.0, "kind": "level", "level": "L1"},
            {"t": 2.0, "kind": "shift", "level": floor, "xy": [1.0, 1.0]},
            {"t": 3.0, "kind": "summary", "floor": floor, "reached": True},
        ]) + '\n')
        verdict = {"passed": ["stop and recheck"], "failed": []}
        return verdict, path

    monkeypatch.setattr(run_b2, "run", run)
    seen = []
    isolated_bus.subscribe("log/decision", seen.append)
    with TestClient(hub.app) as client:
        started = client.post("/run/rescue", json={"seed": 7, "floors": ["B1"]})
        assert started.status_code == 202, started.text
        assert entered.wait(1)
        assert started.json()["state"] == "running"
        assert client.get("/run").json()["state"] == "running"
        assert client.post("/run/rescue").status_code == 409
        release.set()
        finished = until_finished(client)
        assert finished == {"state": "done", "floor": "B1", "t": 3.0,
                            "log": "runs/chain-7.jsonl",
                            "verdict": {"passed": ["B1: stop and recheck"], "failed": []}}
    log = [json.loads(line) for line in (tmp_path / "runs" / "chain-7.jsonl").read_text().splitlines()]
    assert [r["kind"] for r in log] == ["meta", "level", "shift", "leg_summary", "leg", "summary"]
    forwarded = [json.loads(msg["reason"]) for msg in seen]
    assert [r["kind"] for r in forwarded] == [r["kind"] for r in log]
    assert [msg["t"] for msg in seen] == [r["t"] for r in log]


def test_get_is_idle_and_invalid_posts_do_not_start(isolated_bus, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "tools.run_chain", fake_chain())
    with TestClient(hub.app) as client:
        assert client.get("/run").json() == {"state": "idle", "floor": None, "t": 0.0,
                                             "log": None, "verdict": None}
        for body in ({"seed": True}, {"seed": -1}, {"floors": []}, {"floors": ["B4"]},
                     {"floors": ["B2", "B1"]}, {"extra": 1}):
            assert client.post("/run/rescue", json=body).status_code == 400
        assert client.post("/run/rescue", content=b"{", headers={"content-type": "application/json"}).status_code == 400
        assert client.get("/run").json()["state"] == "idle"
        assert not list(tmp_path.rglob("*.jsonl"))


def test_runner_error_reaches_failed_state_and_releases_the_run(isolated_bus, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "tools.run_chain", fake_chain())

    def broken_run(**_):
        raise RuntimeError("synthetic runner failure")

    monkeypatch.setattr(run_b2, "run", broken_run)
    with TestClient(hub.app) as client:
        assert client.post("/run/rescue", json={"floors": ["B1"]}).status_code == 202
        failed = until_finished(client)
        assert failed["state"] == "failed" and failed["verdict"] == {
            "passed": [], "failed": ["runner error"]}
        assert json.loads((tmp_path / failed["log"]).read_text())["kind"] == "error"
        assert client.post("/run/rescue", json={"floors": ["B1"]}).status_code == 202
