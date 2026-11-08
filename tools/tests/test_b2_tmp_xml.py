"""B2-TMP-XML: each run_b2 scene is its own file, so parallel runs in one out_dir can't clobber each other."""
from tools.run_b2 import scene_with_slab


def test_each_call_gets_its_own_scene_file(tmp_path):
    a = scene_with_slab(tmp_path)
    b = scene_with_slab(tmp_path)
    assert a != b
    assert a.parent == b.parent == tmp_path
    assert a.name != "levels_with_slab.xml" and b.name != "levels_with_slab.xml"
    for p in (a, b):
        assert 'name="x1_slab"' in p.read_text(encoding="utf-8")


def test_scene_loads_in_mujoco(tmp_path):
    from sim.levels import LevelWorld

    w = LevelWorld(path=scene_with_slab(tmp_path), render=False)
    assert w.m.body("x1").id >= 0
