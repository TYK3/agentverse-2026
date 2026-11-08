"""FLOOR-DWELL: in a real descent log the Scout dwells on each floor for a positive, bounded time (ref b3).

How long the Scout stays on each floor of a tools/run_b2.py log, from its `level` records: a floor's dwell
runs from the record that reached it to the next floor's (the last floor's to the summary). Checked:
- every floor on the way down is dwelt on for more than 0 s (no floor skipped or passed in no time),
- no floor takes longer than MAX_DWELL_S: the Scout never sits stuck on a floor,
- the dwells add up to the run's time, and every logged pose during a floor's dwell is on that floor or
  on a ramp (the `level` field of the pose records), never on another floor.
MAX_DWELL_S is 120 s, about 1.5 times the longest real dwell (B1, 77.0 s in the B3 run below).

Real logs: REAL (seed 0 on main, both 9/9): the level and summary records and every pose's (t, level)
of a B2 run and a B3 run; plus, when available, the newest full runs/b2-*.jsonl and runs/b3-*.jsonl (or
$B2_LOG / $B3_LOG); those skip otherwise (CI has none).
"""

import json
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
MAX_DWELL_S = 120.0
PATH = {"B2": ["L1", "ground", "B1", "B2"], "B3": ["L1", "ground", "B1", "B2", "B3"]}

REAL = {
    'b2-0': {
        'records': [{'t': 0.0, 'kind': 'level', 'level': 'L1'}, {'t': 21.6, 'kind': 'level', 'level': 'ground'}, {'t': 80.1, 'kind': 'level', 'level': 'B1'}, {'t': 155.3, 'kind': 'level', 'level': 'B2'}, {'t': 179.3, 'kind': 'summary', 'floor': 'B2', 'reached': True, 'final_level': 'B2'}],
        'poses': [(0.0, 'L1'), (1.0, 'L1'), (2.0, 'L1'), (3.0, 'L1'), (4.0, 'L1'), (5.0, 'L1'), (6.0, 'L1'), (7.0, 'L1'), (8.0, 'L1'), (9.0, 'ramp'), (10.0, 'ramp'), (11.0, 'ramp'), (12.0, 'ramp'), (13.0, 'ramp'), (14.0, 'ramp'), (15.0, 'ramp'), (16.0, 'ramp'), (17.0, 'ramp'), (18.0, 'ramp'), (19.0, 'ramp'), (20.0, 'ramp'), (21.0, 'ramp'), (22.0, 'ground'), (23.0, 'ground'), (24.0, 'ground'), (25.0, 'ground'), (26.0, 'ground'), (27.0, 'ground'), (28.0, 'ground'), (29.0, 'ground'), (30.0, 'ground'), (31.0, 'ground'), (32.0, 'ground'), (33.0, 'ground'), (34.0, 'ground'), (35.0, 'ground'), (36.0, 'ground'), (37.0, 'ground'), (38.0, 'ground'), (39.0, 'ground'), (40.0, 'ground'), (41.0, 'ground'), (42.0, 'ground'), (43.0, 'ground'), (44.0, 'ground'), (45.0, 'ground'), (46.0, 'ground'), (47.0, 'ground'), (48.0, 'ground'), (49.0, 'ground'), (50.0, 'ground'), (51.0, 'ground'), (52.0, 'ground'), (53.0, 'ground'), (54.0, 'ground'), (55.0, 'ground'), (56.0, 'ground'), (57.0, 'ground'), (58.0, 'ramp'), (59.0, 'ramp'), (60.0, 'ramp'), (61.0, 'ramp'), (62.0, 'ramp'), (63.0, 'ramp'), (64.0, 'ramp'), (65.0, 'ramp'), (66.0, 'ramp'), (67.0, 'ramp'), (68.0, 'ramp'), (69.0, 'ramp'), (70.0, 'ramp'), (71.0, 'ramp'), (72.0, 'ramp'), (73.0, 'ramp'), (74.0, 'ramp'), (75.0, 'ramp'), (76.0, 'ramp'), (77.0, 'ramp'), (78.0, 'ramp'), (79.0, 'ramp'), (80.0, 'ramp'), (81.0, 'B1'), (82.0, 'B1'), (83.0, 'B1'), (84.0, 'B1'), (85.0, 'B1'), (86.0, 'B1'), (87.0, 'B1'), (88.0, 'B1'), (89.0, 'B1'), (90.0, 'B1'), (91.0, 'B1'), (92.0, 'B1'), (93.0, 'B1'), (94.0, 'B1'), (95.0, 'B1'), (96.0, 'B1'), (97.0, 'B1'), (98.0, 'B1'), (99.0, 'B1'), (100.0, 'B1'), (101.0, 'B1'), (102.0, 'B1'), (103.0, 'B1'), (104.0, 'B1'), (105.0, 'B1'), (106.0, 'B1'), (107.0, 'B1'), (108.0, 'B1'), (109.0, 'B1'), (110.0, 'B1'), (111.0, 'B1'), (112.0, 'B1'), (113.0, 'B1'), (114.0, 'B1'), (115.0, 'B1'), (116.0, 'B1'), (117.0, 'B1'), (118.0, 'B1'), (119.0, 'B1'), (120.0, 'B1'), (121.0, 'B1'), (122.0, 'B1'), (123.0, 'B1'), (124.0, 'B1'), (125.0, 'B1'), (126.0, 'B1'), (127.0, 'B1'), (128.0, 'B1'), (129.0, 'B1'), (130.0, 'B1'), (131.0, 'B1'), (132.0, 'B1'), (133.0, 'B1'), (134.0, 'B1'), (135.0, 'B1'), (136.0, 'B1'), (137.0, 'B1'), (138.0, 'B1'), (139.0, 'B1'), (140.0, 'B1'), (141.0, 'ramp'), (142.0, 'ramp'), (143.0, 'ramp'), (144.0, 'ramp'), (145.0, 'ramp'), (146.0, 'ramp'), (147.0, 'ramp'), (148.0, 'ramp'), (149.0, 'ramp'), (150.0, 'ramp'), (151.0, 'ramp'), (152.0, 'ramp'), (153.0, 'ramp'), (154.0, 'ramp'), (155.0, 'ramp'), (156.0, 'B2'), (157.0, 'B2'), (158.0, 'B2'), (159.0, 'B2'), (160.0, 'B2'), (161.0, 'B2'), (162.0, 'B2'), (163.0, 'B2'), (164.0, 'B2'), (165.0, 'B2'), (166.0, 'B2'), (167.0, 'B2'), (168.0, 'B2'), (169.0, 'B2'), (170.0, 'B2'), (171.0, 'B2'), (172.0, 'B2'), (173.0, 'B2'), (174.0, 'B2'), (175.0, 'B2'), (176.0, 'B2'), (177.0, 'B2'), (178.0, 'B2'), (179.0, 'B2')],
    },
    'b3-0': {
        'records': [{'t': 0.0, 'kind': 'level', 'level': 'L1'}, {'t': 21.6, 'kind': 'level', 'level': 'ground'}, {'t': 65.9, 'kind': 'level', 'level': 'B1'}, {'t': 142.9, 'kind': 'level', 'level': 'B2'}, {'t': 217.0, 'kind': 'level', 'level': 'B3'}, {'t': 230.9, 'kind': 'summary', 'floor': 'B3', 'reached': True, 'final_level': 'B3'}],
        'poses': [(0.0, 'L1'), (1.0, 'L1'), (2.0, 'L1'), (3.0, 'L1'), (4.0, 'L1'), (5.0, 'L1'), (6.0, 'L1'), (7.0, 'L1'), (8.0, 'L1'), (9.0, 'ramp'), (10.0, 'ramp'), (11.0, 'ramp'), (12.0, 'ramp'), (13.0, 'ramp'), (14.0, 'ramp'), (15.0, 'ramp'), (16.0, 'ramp'), (17.0, 'ramp'), (18.0, 'ramp'), (19.0, 'ramp'), (20.0, 'ramp'), (21.0, 'ramp'), (22.0, 'ground'), (23.0, 'ground'), (24.0, 'ground'), (25.0, 'ground'), (26.0, 'ground'), (27.0, 'ground'), (28.0, 'ground'), (29.0, 'ground'), (30.0, 'ground'), (31.0, 'ground'), (32.0, 'ground'), (33.0, 'ground'), (34.0, 'ground'), (35.0, 'ground'), (36.0, 'ground'), (37.0, 'ground'), (38.0, 'ground'), (39.0, 'ground'), (40.0, 'ground'), (41.0, 'ground'), (42.0, 'ground'), (43.0, 'ground'), (44.0, 'ground'), (45.0, 'ground'), (46.0, 'ground'), (47.0, 'ground'), (48.0, 'ground'), (49.0, 'ground'), (50.0, 'ground'), (51.0, 'ground'), (52.0, 'ground'), (53.0, 'ground'), (54.0, 'ground'), (55.0, 'ramp'), (56.0, 'ramp'), (57.0, 'ramp'), (58.0, 'ramp'), (59.0, 'ramp'), (60.0, 'ramp'), (61.0, 'ramp'), (62.0, 'ramp'), (63.0, 'ramp'), (64.0, 'ramp'), (65.0, 'ramp'), (66.0, 'B1'), (67.0, 'B1'), (68.0, 'B1'), (69.0, 'B1'), (70.0, 'B1'), (71.0, 'B1'), (72.0, 'B1'), (73.0, 'B1'), (74.0, 'B1'), (75.0, 'B1'), (76.0, 'B1'), (77.0, 'B1'), (78.0, 'B1'), (79.0, 'B1'), (80.0, 'B1'), (81.0, 'B1'), (82.0, 'B1'), (83.0, 'B1'), (84.0, 'B1'), (85.0, 'B1'), (86.0, 'B1'), (87.0, 'B1'), (88.0, 'B1'), (89.0, 'B1'), (90.0, 'B1'), (91.0, 'B1'), (92.0, 'B1'), (93.0, 'B1'), (94.0, 'B1'), (95.0, 'B1'), (96.0, 'B1'), (97.0, 'B1'), (98.0, 'B1'), (99.0, 'B1'), (100.0, 'B1'), (101.0, 'B1'), (102.0, 'B1'), (103.0, 'B1'), (104.0, 'B1'), (105.0, 'B1'), (106.0, 'B1'), (107.0, 'B1'), (108.0, 'B1'), (109.0, 'B1'), (110.0, 'B1'), (111.0, 'B1'), (112.0, 'B1'), (113.0, 'B1'), (114.0, 'B1'), (115.0, 'B1'), (116.0, 'B1'), (117.0, 'B1'), (118.0, 'B1'), (119.0, 'B1'), (120.0, 'B1'), (121.0, 'B1'), (122.0, 'B1'), (123.0, 'B1'), (124.0, 'B1'), (125.0, 'B1'), (126.0, 'B1'), (127.0, 'B1'), (128.0, 'B1'), (129.0, 'B1'), (130.0, 'B1'), (131.0, 'B1'), (132.0, 'B1'), (133.0, 'B1'), (134.0, 'ramp'), (135.0, 'ramp'), (136.0, 'ramp'), (137.0, 'ramp'), (138.0, 'ramp'), (139.0, 'ramp'), (140.0, 'ramp'), (141.0, 'ramp'), (142.0, 'ramp'), (143.0, 'B2'), (144.0, 'B2'), (145.0, 'B2'), (146.0, 'ramp'), (147.0, 'ramp'), (148.0, 'ramp'), (149.0, 'ramp'), (150.0, 'B2'), (151.0, 'B2'), (152.0, 'B2'), (153.0, 'B2'), (154.0, 'B2'), (155.0, 'B2'), (156.0, 'B2'), (157.0, 'B2'), (158.0, 'B2'), (159.0, 'B2'), (160.0, 'B2'), (161.0, 'B2'), (162.0, 'B2'), (163.0, 'B2'), (164.0, 'B2'), (165.0, 'B2'), (166.0, 'B2'), (167.0, 'B2'), (168.0, 'B2'), (169.0, 'B2'), (170.0, 'B2'), (171.0, 'B2'), (172.0, 'B2'), (173.0, 'B2'), (174.0, 'B2'), (175.0, 'B2'), (176.0, 'B2'), (177.0, 'B2'), (178.0, 'B2'), (179.0, 'B2'), (180.0, 'B2'), (181.0, 'B2'), (182.0, 'B2'), (183.0, 'B2'), (184.0, 'B2'), (185.0, 'B2'), (186.0, 'B2'), (187.0, 'B2'), (188.0, 'B2'), (189.0, 'B2'), (190.0, 'B2'), (191.0, 'B2'), (192.0, 'B2'), (193.0, 'B2'), (194.0, 'B2'), (195.0, 'B2'), (196.0, 'B2'), (197.0, 'B2'), (198.0, 'B2'), (199.0, 'B2'), (200.0, 'B2'), (201.0, 'B2'), (202.0, 'B2'), (203.0, 'B2'), (204.0, 'B2'), (205.0, 'B2'), (206.0, 'B2'), (207.0, 'ramp'), (208.0, 'ramp'), (209.0, 'ramp'), (210.0, 'ramp'), (211.0, 'ramp'), (212.0, 'ramp'), (213.0, 'ramp'), (214.0, 'ramp'), (215.0, 'ramp'), (216.0, 'ramp'), (217.0, 'B3'), (218.0, 'B3'), (219.0, 'B3'), (220.0, 'B3'), (221.0, 'B3'), (222.0, 'B3'), (223.0, 'B3'), (224.0, 'B3'), (225.0, 'B3'), (226.0, 'B3'), (227.0, 'B3'), (228.0, 'B3'), (229.0, 'B3'), (230.0, 'B3')],
    },
}


def dwell(records):
    """[(floor, start t, dwell s)] from the level records, the last floor ending at the summary."""
    levels = [(r["t"], r["level"]) for r in records if r.get("kind") == "level"]
    end = next((r["t"] for r in records if r.get("kind") == "summary"), None)
    out = []
    for i, (t, floor) in enumerate(levels):
        nxt = levels[i + 1][0] if i + 1 < len(levels) else end
        out.append((floor, t, None if nxt is None else round(nxt - t, 2)))
    return out


def check(records, poses):
    summary = next(r for r in records if r.get("kind") == "summary")
    d = dwell(records)
    assert [f for f, _, _ in d] == PATH[summary["floor"]], d
    assert all(s is not None and s > 0 for _, _, s in d), f"a floor passed in no time: {d}"
    assert all(s <= MAX_DWELL_S for _, _, s in d), f"stuck on a floor longer than {MAX_DWELL_S} s: {d}"
    assert sum(s for _, _, s in d) == pytest.approx(summary["t"] - d[0][1], abs=0.05)
    spans = [(f, t, t + s) for f, t, s in d]
    for t, level in poses:
        floor = next((f for f, a, b in spans if a <= t < b or (f == spans[-1][0] and t == b)), None)
        assert level in (floor, "ramp"), f"pose at {t} s on {level} while dwelling on {floor}"
    return {f: s for f, _, s in d}


@pytest.mark.parametrize("name", list(REAL))
def test_real_logs_dwell_on_every_floor(name):
    got = check(REAL[name]["records"], REAL[name]["poses"])
    print(f"{name}: {got}")
    assert len(got) == len(PATH["B3" if name.startswith("b3") else "B2"])


@pytest.mark.parametrize("floor", ["b2", "b3"])
def test_full_real_logs(floor):
    env = os.environ.get(f"{floor.upper()}_LOG")
    found = [pathlib.Path(env)] if env else sorted((ROOT / "runs").glob(f"{floor}-*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not found:
        pytest.skip(f"no full {floor.upper()} log")
    records = [json.loads(line) for line in found[-1].read_text(encoding="utf-8").splitlines() if line.strip()]
    poses = [(r["t"], r["level"]) for r in records if r.get("kind") == "pose"]
    print(f"{found[-1].name}: {check(records, poses)}")


def _log(times, end, floor="B2"):
    recs = [{"t": t, "kind": "level", "level": lv} for t, lv in zip(times, PATH[floor], strict=False)]
    return recs + [{"t": end, "kind": "summary", "floor": floor, "reached": True, "final_level": floor}]


def test_a_clean_descent_passes():
    assert check(_log([0, 20, 60, 130], 150), [(10, "L1"), (40, "ramp"), (70, "B1"), (140, "B2")]) == \
        {"L1": 20, "ground": 40, "B1": 70, "B2": 20}


@pytest.mark.parametrize("times,end,poses", [
    ([0, 20, 20, 130], 150, []),                       # B1 passed in no time
    ([0, 20, 60, 200], 210, []),                       # 140 s on B1: stuck
    ([0, 20, 60, 130], 130, []),                       # no time on the last floor
    ([0, 20, 60], 150, []),                            # never reached B2
    ([0, 20, 60, 130], 150, [(70, "L1")]),             # a pose on L1 while on B1
])
def test_broken_descents_fail(times, end, poses):
    with pytest.raises(AssertionError):
        check(_log(times, end), poses)
