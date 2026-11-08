"""RUN-CANCEL: stopping a rescue must prevent late completion and log delivery."""

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


@pytest.mark.xfail(strict=True, reason="hub has no /run/cancel route or killable leg worker yet")
def test_cancel_active_rescue_prevents_late_done_and_records(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    target_bus = hub.Bus()
    monkeypatch.setattr(hub, "bus", target_bus)
    monkeypatch.setattr(hub, "LANES", ())
    original = hub.importlib.import_module

    def imports(name):
        if name == "coord.gem":
            raise ModuleNotFoundError(name=name)
        return original(name)

    monkeypatch.setattr(hub.importlib, "import_module", imports)

    def leg_records(path):
        return [json.loads(line) for line in Path(path).read_text().splitlines()]

    def chain(legs, seed):
        return [{"t": 0.0, "kind": "meta", "seed": seed},
                {"t": 2.0, "kind": "summary", "passed": len(legs), "failed": []}]

    monkeypatch.setitem(sys.modules, "tools.run_chain", SimpleNamespace(
        leg_records=leg_records, chain=chain, CASUALTY={"B1": "c1"}))
    entered, release = threading.Event(), threading.Event()

    def run(seed, out_dir, floor, **_):
        entered.set()
        assert release.wait(5), "test did not release the worker"
        path = Path(out_dir) / f"{floor.lower()}-{seed}.jsonl"
        path.write_text(json.dumps({"t": 2.0, "kind": "summary", "floor": floor,
                                    "reached": True}) + "\n")
        return {"passed": ["reached casualty"], "failed": []}, path

    monkeypatch.setattr(run_b2, "run", run)
    seen = []
    target_bus.subscribe("log/decision", seen.append)
    with TestClient(hub.app) as client:
        try:
            started = client.post("/run/rescue", json={"floors": ["B1"]})
            assert started.status_code == 202, started.text
            assert entered.wait(1)
            before = len(seen)

            cancelled = client.post("/run/cancel")
            assert cancelled.status_code in {200, 202}, cancelled.text
            release.set()  # A late worker result must not turn cancellation into success.

            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                status = client.get("/run").json()
                if status["state"] != "running":
                    break
                time.sleep(0.01)
            assert status["state"] in {"idle", "failed"}, status
            if status["state"] == "failed":
                assert any("cancel" in reason.lower() for reason in status["verdict"]["failed"])
            time.sleep(0.05)
            assert client.get("/run").json()["state"] != "done"
            assert len(seen) == before, "cancelled run published late records"
        finally:
            release.set()
