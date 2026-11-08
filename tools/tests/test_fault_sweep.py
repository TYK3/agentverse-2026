"""tools/fault_sweep.py: fault filters and a mocked-subprocess sweep (no real rescue runs)."""

import asyncio
import random
import subprocess
import types

from tools import fault_sweep as fs


def repo(tmp_path, script=True):
    if script:
        (tmp_path / "tools").mkdir(parents=True)
        (tmp_path / "tools" / "run_rescue.py").write_text("")
    return tmp_path


def test_dropout_drops_some_scout_frames_only():
    f = fs.fault_filter("dropout", random.Random(1))
    kept = [f("sensors/scout", {"t": i}) for i in range(200)]
    dropped = sum(k is None for k in kept)
    assert 30 < dropped < 90
    assert f("map/cells", {"x": 1}) == {"x": 1}


def test_noise_perturbs_lidar_and_points_not_in_place():
    frame = {"lidar": [1.0, 2.0], "points": [[0.0, 0.0, 0.0]], "pose": {"pos": [0, 0, 0]}}
    out = fs.fault_filter("noise", random.Random(2))("sensors/scout", frame)
    assert out["lidar"] != [1.0, 2.0] and out["points"] != [[0.0, 0.0, 0.0]]
    assert frame["lidar"] == [1.0, 2.0] and out["pose"] == frame["pose"]


def test_casualty_offset_moves_pos():
    out = fs.fault_filter("casualty_offset", random.Random(0))(
        "map/casualties", [{"id": "c1", "pos": [1.0, 1.0, 0.0]}])
    assert out[0]["pos"] == [1.3, 1.0, 0.0] and out[0]["id"] == "c1"


def test_baseline_passes_everything():
    f = fs.fault_filter("baseline", random.Random(0))
    assert f("sensors/scout", {"a": 1}) == {"a": 1}


def test_install_wraps_bus(monkeypatch):
    from coord import hub

    got = []

    async def orig(self, topic, data):
        got.append((topic, data))

    monkeypatch.setattr(hub.Bus, "publish", orig)
    fs.install("casualty_offset", 0)
    asyncio.run(hub.Bus.publish(object(), "map/casualties", [{"id": "c1", "pos": [0, 0, 0]}]))
    assert got == [("map/casualties", [{"id": "c1", "pos": [0.3, 0.0, 0.0]}])]


def test_late_shift_command():
    cmd = fs.command("late_shift", 3)
    assert cmd[cmd.index("--child") + 1] == "late_shift"
    assert "--drive-before" in cmd and "--auto-approve" in cmd and cmd[-1] == str(fs.LATE_DRIVE)


def fake(outcomes, calls):
    def runner(cmd, **kw):
        fault = cmd[cmd.index("--child") + 1]
        calls.append((fault, kw))
        o = outcomes[fault]
        if o == "timeout":
            raise subprocess.TimeoutExpired(cmd, kw["timeout"], output=b"exploring")
        return types.SimpleNamespace(returncode=o[0], stdout=o[1], stderr="")
    return runner


def test_sweep_rates_and_table(tmp_path):
    calls = []
    run = fake({"baseline": (0, "15/15 steps passed"), "dropout": (1, "12/15 steps passed"),
                "noise": "timeout"}, calls)
    rows, rates = fs.sweep(["baseline", "dropout", "noise"], [1], 5, repo(tmp_path), run)
    assert rates == {"baseline": 1.0, "dropout": 0.0, "noise": 0.0}
    assert [r["status"] for r in rows] == ["pass", "fail", "timeout"]
    assert calls[0][1]["env"]["GEMINI_MODE"] == "off" and calls[0][1]["timeout"] == 5
    md = fs.section(rows, rates)
    assert "| baseline | 1/1 = 100% | 1 |" in md and "| dropout | 1 | FAIL |" in md


def test_missing_script_skips(tmp_path):
    rows, rates = fs.sweep(["baseline"], [1, 2], root=repo(tmp_path, script=False),
                           runner=lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert {r["status"] for r in rows} == {"skipped"} and rates == {"baseline": None}
    assert "n/a (skipped)" in fs.section(rows, rates)


def test_main_exit_and_section_replace(tmp_path):
    root = repo(tmp_path)
    out = root / "runs" / "full_test.md"
    out.parent.mkdir()
    out.write_text("# Full test run\n\nkeep\n")
    ok = fake({"baseline": (0, "ok")}, [])
    assert fs.main(["--faults", "baseline", "--output", str(out)], root=root, runner=ok) == 0
    bad = fake({"baseline": (1, "")}, [])
    assert fs.main(["--faults", "baseline", "--output", str(out)], root=root, runner=bad) == 1
    text = out.read_text()
    assert text.startswith("# Full test run") and "keep" in text and text.count(fs.BEGIN) == 1
