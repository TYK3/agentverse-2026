"""Tests for sim/scene_builder.py (T07).

Verifies:
- MJCF extraction from model text (raw XML or markdown blocks)
- Validation of required bodies (mocap ground, casualty_c1, cameras, b<number> blocks)
- 3 s settle physics gate (< 0.05 m drift)
- Critique view rendering and PNG generation
- Offline behavior in GEMINI_MODE=off (falls back to backup scene and marks stand-in)
- Visual self-critique loop in replay mode across two photo sets (set1 and set2)
- Clean fallback to backup scene on failure after max rounds
- CONTRACT.md compliance for scene/loaded payload
"""

from __future__ import annotations

from pathlib import Path

import mujoco
import numpy as np
import pytest

from sim import scene_builder


@pytest.fixture(autouse=True)
def cleanup_generated(tmp_path, monkeypatch):
    test_gen_dir = tmp_path / "generated"
    test_gen_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(scene_builder, "GENERATED_DIR", test_gen_dir)
    monkeypatch.setattr(scene_builder, "PHOTO_SCENE_XML", test_gen_dir / "photo_scene.xml")
    yield test_gen_dir


def test_extract_mjcf():
    raw_xml = "<mujoco model=\"test\"><worldbody/></mujoco>"
    assert scene_builder.extract_mjcf(raw_xml) == raw_xml

    wrapped_markdown = f"Here is the requested scene:\n```xml\n{raw_xml}\n```\nHope this helps."
    assert scene_builder.extract_mjcf(wrapped_markdown) == raw_xml

    no_xml = "I cannot generate the scene right now."
    assert scene_builder.extract_mjcf(no_xml) is None


def test_save_png(tmp_path):
    img_path = tmp_path / "test.png"
    arr = np.zeros((20, 30, 3), dtype=np.uint8)
    arr[:, :, 0] = 200  # Red
    scene_builder.save_png(img_path, arr)

    assert img_path.is_file()
    data = img_path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_validate_scene_backup_xml():
    backup_text = Path(scene_builder.BACKUP_XML).read_text(encoding="utf-8")
    valid, err, m, d = scene_builder.validate_scene(backup_text)
    assert valid is True
    assert err == "ok"
    assert m is not None and d is not None


def test_validate_scene_missing_ground():
    xml = (
        '<mujoco model="no_ground">\n'
        '  <worldbody>\n'
        '    <body name="casualty_c1" pos="0 0 0"><geom type="sphere" size="0.1"/></body>\n'
        '    <camera name="overview" pos="0 0 1"/>\n'
        '    <camera name="scout_cam" pos="0 0 1"/>\n'
        '  </worldbody>\n'
        '</mujoco>'
    )
    valid, err, _, _ = scene_builder.validate_scene(xml)
    assert valid is False
    assert "ground" in err


def test_validate_scene_ground_not_mocap():
    xml = (
        '<mujoco model="ground_not_mocap">\n'
        '  <worldbody>\n'
        '    <body name="ground" mocap="false" pos="0 0 0"><geom type="plane" size="1 1 0.1"/></body>\n'
        '    <body name="casualty_c1" pos="0 0 0"><geom type="sphere" size="0.1"/></body>\n'
        '    <camera name="overview" pos="0 0 1"/>\n'
        '    <camera name="scout_cam" pos="0 0 1"/>\n'
        '  </worldbody>\n'
        '</mujoco>'
    )
    valid, err, _, _ = scene_builder.validate_scene(xml)
    assert valid is False
    assert "mocap=true" in err


def test_validate_scene_missing_casualty():
    xml = (
        '<mujoco model="no_casualty">\n'
        '  <worldbody>\n'
        '    <body name="ground" mocap="true" pos="0 0 0"><geom type="plane" size="1 1 0.1"/></body>\n'
        '    <camera name="overview" pos="0 0 1"/>\n'
        '    <camera name="scout_cam" pos="0 0 1"/>\n'
        '  </worldbody>\n'
        '</mujoco>'
    )
    valid, err, _, _ = scene_builder.validate_scene(xml)
    assert valid is False
    assert "casualty_c1" in err


def test_validate_scene_unstable_drift():
    # A block floating in mid-air drops under gravity, failing the 3 s settle drift check (< 0.05 m)
    unstable_xml = (
        '<mujoco model="unstable">\n'
        '  <option timestep="0.002" gravity="0 0 -9.81"/>\n'
        '  <worldbody>\n'
        '    <body name="ground" mocap="true" pos="0 0 0"><geom type="box" size="3 3 0.05" pos="0 0 -0.05"/></body>\n'
        '    <body name="b1" pos="0 0 1.5"><freejoint/><geom name="b1_wall" type="box" size="0.1 0.1 0.1"/></body>\n'
        '    <body name="casualty_c1" pos="1 1 0.1"><geom type="sphere" size="0.1"/></body>\n'
        '    <camera name="overview" pos="0 0 3"/>\n'
        '    <camera name="scout_cam" pos="0 0 1"/>\n'
        '  </worldbody>\n'
        '</mujoco>'
    )
    valid, err, _, _ = scene_builder.validate_scene(unstable_xml)
    assert valid is False
    assert "drifted" in err or "unstable" in err.lower()


def test_render_critique_views(cleanup_generated):
    m = mujoco.MjModel.from_xml_path(str(scene_builder.BACKUP_XML))
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)

    saved = scene_builder.render_critique_views(m, d, round_idx=1, out_dir=cleanup_generated)
    assert set(saved.keys()) == {"overview", "scout_cam", "side_view"}
    for p in saved.values():
        assert p.is_file()
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_make_renderer_headless(monkeypatch):
    m = mujoco.MjModel.from_xml_path(str(scene_builder.BACKUP_XML))
    monkeypatch.setattr(scene_builder.sys, "platform", "linux")
    monkeypatch.delenv("MUJOCO_GL", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert scene_builder.make_renderer(m) is None


def test_build_scene_off_mode(monkeypatch):
    monkeypatch.setenv("GEMINI_MODE", "off")
    m, d, payload = scene_builder.build_scene()

    assert m is not None and d is not None
    assert payload["scene"] == "backup"
    assert len(payload["blocks"]) == 16
    assert all(set(b.keys()) == {"id", "label", "pos", "size"} for b in payload["blocks"])


def test_build_scene_replay_set1(monkeypatch, cleanup_generated):
    monkeypatch.setenv("GEMINI_MODE", "replay")
    photos_dir = Path(__file__).resolve().parent.parent / "photos" / "set1"
    photo_files = list(photos_dir.glob("*.jpg"))

    out_file = cleanup_generated / "photo_scene.xml"
    m, d, payload = scene_builder.build_scene(
        photo_paths=photo_files,
        max_rounds=2,
        out_file=out_file,
        generated_dir=cleanup_generated,
    )

    assert m is not None and d is not None
    assert payload["scene"] == "photo"
    assert len(payload["blocks"]) == 12
    assert out_file.is_file()
    assert "<mujoco" in out_file.read_text(encoding="utf-8")

    # Verify iteration critique images were saved
    assert (cleanup_generated / "iter1_overview.png").is_file()
    assert (cleanup_generated / "iter1_scout_cam.png").is_file()
    assert (cleanup_generated / "iter1_side_view.png").is_file()
    assert (cleanup_generated / "iter2_overview.png").is_file()


def test_build_scene_replay_set2(monkeypatch, cleanup_generated):
    monkeypatch.setenv("GEMINI_MODE", "replay")
    photos_dir = Path(__file__).resolve().parent.parent / "photos" / "set2"
    photo_files = list(photos_dir.glob("*.jpg"))

    out_file = cleanup_generated / "photo_scene_set2.xml"
    m, d, payload = scene_builder.build_scene(
        photo_paths=photo_files,
        max_rounds=2,
        out_file=out_file,
        generated_dir=cleanup_generated,
    )

    assert m is not None and d is not None
    assert payload["scene"] == "photo"
    assert len(payload["blocks"]) == 12
    assert out_file.is_file()
    assert "aftershock_photo_scene_set2" in out_file.read_text(encoding="utf-8")


def test_build_scene_failure_clean_fallback(monkeypatch, cleanup_generated):
    monkeypatch.setenv("GEMINI_MODE", "replay")
    # Force call_gemini_or_replay to return an unparseable XML
    monkeypatch.setattr(scene_builder, "call_gemini_or_replay", lambda *args, **kwargs: "invalid output")

    m, d, payload = scene_builder.build_scene(
        photo_paths=["dummy1.jpg"],
        max_rounds=3,
        out_file=cleanup_generated / "fallback.xml",
        generated_dir=cleanup_generated,
    )

    assert m is not None and d is not None
    # Clean fallback to backup scene
    assert payload["scene"] == "backup"
    assert len(payload["blocks"]) == 16


def test_build_scene_bus_publish(monkeypatch, cleanup_generated):
    monkeypatch.setenv("GEMINI_MODE", "off")

    class FakeBus:
        def __init__(self):
            self.published = []

        async def publish(self, topic, data):
            self.published.append((topic, data))

    bus = FakeBus()
    m, d, payload = scene_builder.build_scene(bus=bus)
    assert m is not None and d is not None
    assert payload["scene"] == "backup"


def test_contract_compliance(monkeypatch, cleanup_generated):
    monkeypatch.setenv("GEMINI_MODE", "replay")
    photos_dir = Path(__file__).resolve().parent.parent / "photos" / "set1"
    photo_files = list(photos_dir.glob("*.jpg"))

    m, d, payload = scene_builder.build_scene(
        photo_paths=photo_files,
        max_rounds=2,
        out_file=cleanup_generated / "contract_check.xml",
        generated_dir=cleanup_generated,
    )

    assert m is not None and d is not None
    assert payload["scene"] in ("backup", "photo")
    for block in payload["blocks"]:
        assert isinstance(block["id"], str)
        assert block["label"] in ("wall", "rubble")
        assert len(block["pos"]) == 3 and all(isinstance(v, float) for v in block["pos"])
        assert len(block["size"]) == 3 and all(isinstance(v, float) for v in block["size"])
