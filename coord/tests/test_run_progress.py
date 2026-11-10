"""RUN-PROGRESS: GET /run follows each completed leg of a chained rescue."""

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
def isolated_hub(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hub, "bus", hub.Bus())
    monkeypatch.setattr(hub, "LANES", ())
    original = hub.importlib.import_module

    def imports(name):
        if name == "coord.gem":
            raise ModuleNotFoundError(name=name)
        return original(name)

    monkeypatch.setattr(hub.importlib, "import_module", imports)


def chain_module():
    def leg_records(path):
        return [json.loads(line) for line in Path(path).read_text().splitlines()]

    def chain(legs, seed):
        out = [{"t": 0.0, "kind": "meta", "seed": seed, "legs": [floor for floor, _, _ in legs]}]
        offset = 0.0
        for floor, records, verdict in legs:
            out.extend({**r, "kind": "leg_summary", "leg": floor, "leg_t": r["t"],
                        "t": offset + r["t"]} for r in records)
            offset = out[-1]["t"]
            out.append({"t": offset, "kind": "leg", "floor": floor,
                        "passed": len(verdict["passed"]), "failed": len(verdict["failed"])})
        out.append({"t": offset, "kind": "summary", "passed": len(legs), "failed": []})
        return out

    return SimpleNamespace(leg_records=leg_records, chain=chain,
                           CASUALTY={"B1": "c1", "B2": "c2", "B3": "c3"})


def wait_for(client, floor, t, state="running"):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status = client.get("/run").json()
        if status.get("state") == state and status.get("floor") == floor and status.get("t") == t:
            return status
        time.sleep(0.01)
    raise AssertionError(f"GET /run did not reach {state} {floor} at {t}s: {status}")


def test_floor_and_sim_time_advance_between_real_runner_legs(isolated_hub, monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "tools.run_chain", chain_module())
    durations = {"B1": 2.0, "B2": 3.0, "B3": 4.0}
    entered = {floor: threading.Event() for floor in durations}
    release = {floor: threading.Event() for floor in durations}

    def run(seed, out_dir, floor, **_):
        entered[floor].set()
        assert release[floor].wait(5), f"{floor} was never released"
        path = Path(out_dir) / f"{floor.lower()}-{seed}.jsonl"
        path.write_text(json.dumps({"t": durations[floor], "kind": "summary", "floor": floor,
                                    "reached": True}) + "\n")
        return {"passed": ["reached casualty"], "failed": []}, path

    monkeypatch.setattr(run_b2, "run", run)
    try:
        with TestClient(hub.app) as client:
            started = client.post("/run/rescue", json={"seed": 3})
            assert started.status_code == 202, started.text
            assert entered["B1"].wait(1)
            assert wait_for(client, "B1", 0.0)["verdict"] is None

            release["B1"].set()
            assert entered["B2"].wait(2)
            assert wait_for(client, "B2", 2.0)["log"] == "runs/chain-3.jsonl"

            release["B2"].set()
            assert entered["B3"].wait(2)
            assert wait_for(client, "B3", 5.0)["verdict"] is None

            release["B3"].set()
            finished = wait_for(client, "B3", 9.0, state="done")
            assert finished["verdict"] == {
                "passed": [f"{floor}: reached casualty" for floor in durations], "failed": []}
    finally:
        for event in release.values():
            event.set()

    records = [json.loads(line) for line in (tmp_path / "runs" / "chain-3.jsonl").read_text().splitlines()]
    assert [r["t"] for r in records if r["kind"] == "leg"] == [2.0, 5.0, 9.0]
