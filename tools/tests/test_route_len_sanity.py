"""ROUTE-LEN-SANITY: after every plan in a real seed-0 B1 and B2 run, the route
length is finite and above 0.

Plan records carry no length field, so route length is defined here as the
polyline length through the centres of the plan's grid cells, in metres:
cells are [i, j, k] with x = i*RES, y = j*RES, z = k*RES (RES from tools.run_b2;
FLOOR_K there documents k as height / RES). A one-cell route therefore has
length 0, and an empty route has no length at all (fails).

Real gap found on seed 0: some "probe" plans (explore status with a frontier
too close to step along, so run_b2 drives to probe_target instead) log a single
cell, i.e. a zero-length route. That is held as a strict xfail; product code is
not changed here. Route ("ok") and multi-cell explore plans must pass outright.
"""

import json
import math
from itertools import pairwise

import pytest

from tools.run_b2 import RES


def route_length(cells):
    if not cells:
        raise AssertionError("empty route")
    pts = [tuple(float(v) * RES for v in c) for c in cells]
    for p in pts:
        assert all(math.isfinite(v) for v in p), f"non-finite cell {p}"
    return sum(math.dist(a, b) for a, b in pairwise(pts))


def check_plan(plan):
    length = plan.get("length")
    if length is None:
        length = route_length(plan.get("cells"))
    assert math.isfinite(length), f"non-finite route length {length} at t={plan.get('t')}"
    assert length > 0, f"route length {length} at t={plan.get('t')} ({plan.get('why')})"
    return length


@pytest.fixture(scope="module")
def plans(tmp_path_factory):
    from tools.run_b2 import run

    mp = pytest.MonkeyPatch()
    mp.setenv("GEMINI_MODE", "off")
    out = {}
    try:
        for floor in ("B1", "B2"):
            _, path = run(seed=0, floor=floor, out_dir=tmp_path_factory.mktemp(floor))
            rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
            out[floor] = [r for r in rows if r.get("kind") == "plan"]
    finally:
        mp.undo()
    return out


def test_synthetic_good_route():
    assert check_plan({"cells": [[0, 0, 0], [1, 0, 0], [1, 1, -1]]}) == pytest.approx(RES * (1 + math.sqrt(2)))


@pytest.mark.parametrize("plan, reason", [
    ({"cells": []}, "empty route"),
    ({"cells": [[3, 4, 0]]}, "route length 0"),
    ({"cells": [[0, 0, 0], [float("nan"), 0, 0]]}, "non-finite cell"),
    ({"cells": [[0, 0, 0], [1, 0, 0]], "length": float("nan")}, "non-finite route length"),
    ({"cells": [[0, 0, 0], [1, 0, 0]], "length": float("inf")}, "non-finite route length"),
    ({"cells": [[0, 0, 0], [1, 0, 0]], "length": 0.0}, "route length 0"),
])
def test_checker_rejects_bad_routes(plan, reason):
    with pytest.raises(AssertionError, match=reason):
        check_plan(plan)


@pytest.mark.parametrize("floor", ["B1", "B2"])
def test_real_route_and_explore_plans_have_positive_length(plans, floor):
    checked = [p for p in plans[floor] if p.get("why") != "probe"]
    assert checked, "no plans"
    for p in checked:
        check_plan(p)


@pytest.mark.parametrize("floor", ["B1", "B2"])
@pytest.mark.xfail(strict=True, reason="real gap: run_b2 logs some seed-0 'probe' plans with a single "
                   "cell (zero-length route; the Scout drives to probe_target, which is not in cells)")
def test_real_probe_plans_have_positive_length(plans, floor):
    probes = [p for p in plans[floor] if p.get("why") == "probe"]
    assert probes, "no probe plans"
    for p in probes:
        check_plan(p)
