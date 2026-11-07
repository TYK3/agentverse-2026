"""Pure input and baseline checks; actual lane execution is separately measured."""

import xml.etree.ElementTree as ET
from pathlib import Path

from tools.eval_sim import seeded_xml, shortest_known_free


def test_real_scene_seed_is_reproducible_and_varies_both_inputs():
    source = (Path(__file__).parents[2] / "sim/scenes/backup.xml").read_bytes()
    first, fingerprint = seeded_xml(source, 0)
    assert (first, fingerprint) == seeded_xml(source, 0)
    second, other = seeded_xml(source, 1)
    assert other != fingerprint
    a = {node.get("name"): node.get("pos") for node in ET.fromstring(first).iter("body")}
    b = {node.get("name"): node.get("pos") for node in ET.fromstring(second).iter("body")}
    assert a["casualty_c1"] != b["casualty_c1"]
    assert all(a[name] != b[name] for name in ("b11", "b12", "b13", "b14", "b15"))
    assert a["b1"] == b["b1"]


def test_naive_uses_inferred_free_but_does_not_cut_blocked_corners():
    records = {(x, y, 0): {"state": "seen", "occupied": False}
               for x in range(3) for y in range(3)}
    records[(1, 0, 0)]["occupied"] = True
    records[(0, 1, 0)]["state"] = "inferred"
    route = shortest_known_free(records, (0, 0, 0), (2, 2, 0))
    assert route[1] == [0, 1, 0]
    assert [1, 0, 0] not in route


def test_unknown_is_not_known_free():
    records = {(0, 0, 0): {"state": "seen", "occupied": False},
               (1, 0, 0): {"state": "unknown", "occupied": False}}
    assert shortest_known_free(records, (0, 0, 0), (1, 0, 0)) is None
