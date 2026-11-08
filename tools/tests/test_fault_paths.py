"""FAULT-TESTS (ref #31): fault injection paths of tools/fault_sweep.py end to end on the real
coord.hub.Bus, plus how the fault, seed and full_test sections share runs/full_test.md."""

import asyncio
import random

import pytest

from coord import hub
from tools import fault_sweep as fs
from tools import seed_sweep as ss

SCOUT = {"t": 0.0, "pose": {"pos": [0.0, 0.0, 0.0], "yaw": 0.0}, "lidar": [0.01, 1.0, 6.0],
         "camera": None, "thermal": [[0.1]], "acoustic": {"bearing": 0, "level": 0.5}}
CASUALTIES = [{"id": "c1", "pos": [1.0, 2.0, 0.0], "confidence": 0.8, "clues": ["thermal"],
               "vitals": {"breathing_rate": 14, "simulated": True}}]

# A stand-in run_rescue.py: subscribes like a lane, publishes 100 Scout frames and one casualty
# list through the (possibly faulty) Bus, prints what the lanes received, exits 0.
FAKE_RESCUE = '''
import argparse, json
from coord.hub import Bus

def parse(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int); p.add_argument("--auto-approve", action="store_true")
    p.add_argument("--drive-before", type=float, default=0.3)
    return p.parse_args(argv)

async def main(args):
    bus, got = Bus(), {"scout": [], "cas": []}
    bus.subscribe("sensors/scout", lambda d: got["scout"].append(d["lidar"]))
    bus.subscribe("map/casualties", lambda d: got["cas"].append(d[0]["pos"]))
    for i in range(100):
        await bus.publish("sensors/scout", dict(FRAME, t=float(i)))
    await bus.publish("map/casualties", CAS)
    print(json.dumps({"frames": len(got["scout"]), "lidar0": got["scout"][0],
                      "cas": got["cas"][0], "drive": args.drive_before, "seed": args.seed}))
    return 0
'''


@pytest.fixture
def restore_bus(monkeypatch):
    monkeypatch.setattr(hub.Bus, "publish", hub.Bus.publish)


def fake_root(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "run_rescue.py").write_text(
        f"FRAME = {SCOUT!r}\nCAS = {CASUALTIES!r}\n" + FAKE_RESCUE)
    return tmp_path


def run_child(tmp_path, capsys, fault, seed=1, extra=()):
    code = fs.child(fault, seed, ["--auto-approve", "--seed", str(seed), *extra], fake_root(tmp_path))
    import json
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_child_baseline_delivers_everything(tmp_path, capsys, restore_bus):
    code, got = run_child(tmp_path, capsys, "baseline")
    assert code == 0 and got["frames"] == 100
    assert got["lidar0"] == SCOUT["lidar"] and got["cas"] == [1.0, 2.0, 0.0]


def test_child_dropout_reaches_lanes(tmp_path, capsys, restore_bus):
    _, got = run_child(tmp_path, capsys, "dropout")
    assert 50 <= got["frames"] <= 90          # about 30% of 100 frames dropped
    assert got["cas"] == [1.0, 2.0, 0.0]      # other topics untouched


def test_child_noise_still_passes_bus_validation(tmp_path, capsys, restore_bus):
    _, got = run_child(tmp_path, capsys, "noise")
    assert got["frames"] == 100 and got["lidar0"] != SCOUT["lidar"]
    assert min(got["lidar0"]) >= 0.0          # a range near 0 never goes negative


def test_child_casualty_offset_reaches_lanes(tmp_path, capsys, restore_bus):
    _, got = run_child(tmp_path, capsys, "casualty_offset")
    assert got["cas"] == pytest.approx([1.3, 2.0, 0.0]) and got["frames"] == 100


def test_command_late_shift_args_reach_rescue(tmp_path, capsys, restore_bus):
    cmd = fs.command("late_shift", 4)
    rescue_args = cmd[cmd.index("--") + 1:]
    _, got = run_child(tmp_path, capsys, "late_shift", 4, rescue_args[3:])
    assert got["drive"] == fs.LATE_DRIVE and got["seed"] == 4


def test_other_faults_do_not_add_drive_before():
    for fault in ("baseline", "dropout", "noise", "casualty_offset"):
        assert "--drive-before" not in fs.command(fault, 1)


def test_dropout_is_reproducible_per_seed():
    def kept(seed):
        f = fs.fault_filter("dropout", random.Random(seed))
        return [f("sensors/scout", {"t": i}) is not None for i in range(300)]
    assert kept(3) == kept(3) and kept(3) != kept(4)
    assert abs(kept(3).count(False) / 300 - fs.DROPOUT) < 0.1


def test_filters_tolerate_odd_payloads():
    rng = random.Random(0)
    assert fs.fault_filter("noise", rng)("sensors/scout", {"lidar": None}) == {"lidar": None}
    assert fs.fault_filter("noise", rng)("map/casualties", CASUALTIES) == CASUALTIES
    odd = [{"id": "c9"}, "x"]
    assert fs.fault_filter("casualty_offset", rng)("map/casualties", odd) == odd
    assert fs.fault_filter("casualty_offset", rng)("map/casualties", {"not": "a list"}) == {"not": "a list"}


def test_casualty_offset_does_not_mutate_input():
    data = [dict(CASUALTIES[0])]
    fs.fault_filter("casualty_offset", random.Random(0))("map/casualties", data)
    assert data[0]["pos"] == [1.0, 2.0, 0.0]


def test_install_drop_never_calls_original(restore_bus):
    calls = []

    async def orig(self, topic, data):
        calls.append(topic)

    hub.Bus.publish = orig
    fs.DROPOUT, old = 1.0, fs.DROPOUT
    try:
        fs.install("dropout", 0)
        asyncio.run(hub.Bus.publish(object(), "sensors/scout", SCOUT))
        asyncio.run(hub.Bus.publish(object(), "map/cells", {}))
    finally:
        fs.DROPOUT = old
    assert calls == ["map/cells"]


def test_unknown_fault_rejected(tmp_path):
    with pytest.raises(SystemExit, match="unknown fault"):
        fs.main(["--faults", "baseline,earthquake", "--output", str(tmp_path / "r.md")], root=tmp_path)


def test_multiple_seeds_rate_per_fault(tmp_path):
    import types

    def runner(cmd, **kw):
        seed = int(cmd[cmd.index("--fault-seed") + 1])
        return types.SimpleNamespace(returncode=0 if seed % 2 else 1, stdout="x", stderr="")
    root = tmp_path
    (root / "tools").mkdir()
    (root / "tools" / "run_rescue.py").write_text("")
    rows, rates = fs.sweep(["noise"], [1, 2, 3, 4], 5, root, runner)
    assert rates == {"noise": 0.5} and len(rows) == 4
    assert "| noise | 2/4 = 50% | 4 |" in fs.section(rows, rates)


def test_sections_coexist_in_full_test_md(tmp_path):
    path = tmp_path / "runs" / "full_test.md"
    path.parent.mkdir()
    path.write_text("# Full test run\n\n| coord/tests | PASS |\n")
    ss.write_section(path, ss.section([], None))
    fs.write_section(path, fs.section([], {}))
    ss.write_section(path, ss.section([{"seed": 0, "status": "pass", "seconds": 1.0, "reason": "ok"}], 1.0))
    fs.write_section(path, fs.section([], {}))
    text = path.read_text()
    assert text.startswith("# Full test run") and "| coord/tests | PASS |" in text
    assert text.count(ss.BEGIN) == 1 and text.count(fs.BEGIN) == 1
    assert "Success rate: 1/1 = 100%" in text
    assert text.index(ss.BEGIN) < text.index(fs.BEGIN)
