"""Sim-truth rules kept for tests and scoring (perception/score.py): never read at run time (Z1)."""

import pytest

from perception.score import risk, risks, score, truth_cells


def box(id, label, pos, size):
    return {"id": id, "label": label, "pos": list(pos), "size": list(size)}


def test_wall_on_floor_is_stable_and_overhanging_wall_is_at_risk():
    floor_wall = box("b1", "wall", (0, 0, 0.5), (0.05, 0.5, 0.5))
    ledge = box("b2", "rubble", (1.0, 0, 0.05), (0.05, 0.05, 0.05))
    perched = box("b3", "wall", (1.0, 0.3, 0.6), (0.05, 0.4, 0.5))       # base 0.8 m long, 0.1 m on the ledge
    blocks = [floor_wall, ledge, perched]
    assert risk(floor_wall, blocks) is None
    assert risk(perched, blocks).startswith("unsupported wall b3")


def test_rubble_centre_beyond_support_is_at_risk():
    base = box("b1", "rubble", (0, 0, 0.1), (0.1, 0.1, 0.1))
    centred = box("b2", "rubble", (0, 0, 0.25), (0.08, 0.08, 0.05))
    overhang = box("b3", "rubble", (0.2, 0, 0.25), (0.15, 0.08, 0.05))   # centre at x=0.2, support ends at 0.1
    floating = box("b4", "rubble", (2, 2, 0.5), (0.1, 0.1, 0.03))
    blocks = [base, centred, overhang, floating]
    assert risk(centred, blocks) is None
    assert "centre of mass beyond its support" in risk(overhang, blocks)
    assert "nothing beneath" in risk(floating, blocks)


def test_wall_touching_leaning_rubble_is_at_risk():
    wall = box("b1", "wall", (0, 0, 0.5), (0.05, 0.5, 0.5))
    slab = box("b2", "rubble", (-0.3, 0, 0.4), (0.26, 0.2, 0.03))       # nothing beneath, its end on the wall
    other = box("b3", "wall", (-2, 0, 0.5), (0.05, 0.5, 0.5))
    assert set(risks([wall, slab, other])) == {"b1", "b2"}


def test_backup_scene_truth_is_b10_and_b8():
    """#51's shake moves exactly b10 (the slab leaning on b8) and b8: the truth perception is scored on."""
    pytest.importorskip("mujoco")
    from sim import scene
    m, d = scene.load()
    flagged = risks(scene.blocks(m, d))
    assert set(flagged) == {"b10", "b8"}, flagged
    assert flagged["b8"] == "wall b8 carries leaning rubble b10"


def test_score_counts_near_misses():
    blocks = [box("b1", "rubble", (0.0, 0.0, 0.05), (0.05, 0.05, 0.05))]
    truth = truth_cells(blocks, {"b1"})
    assert truth == {(-1, -1), (-1, 0), (0, -1), (0, 0)}
    assert score({(0, 0), (5, 5)}, truth) == {"precision": 0.5, "recall": 0.25, "predicted": 2, "truth": 4}
    assert score({(1, 1)}, truth, near=1)["precision"] == 1.0
    assert score(set(), truth)["recall"] == 0.0
