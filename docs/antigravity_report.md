# Antigravity Independent Verification Report (Task T27 · Job A1)

**Target:** `sim/aftershock.py` (`aftershock_effects`, `unstable_xy`, `verify`)
**Agent:** `[Philbert's Antigravity]` (Antigravity CLI on `gemini-4-argon`, live calls routed through `coord/gem.py`)
**Date:** 8 November 2026

## 1. Summary

Per **T27 (#35) Job A1**, Antigravity performed an independent verification of the MuJoCo physics route verifier (`sim/aftershock.py`) without modifying any simulation code:

1. **Managed sandbox endpoint (`antigravity-preview-09-2026`) check:**
   - Calling `coord.gem.ask_with_receipt("managed_sandbox", ...)` (receipt `gem-5d0781c2b711416d9ff4dcb6335ec6a6`) returned HTTP 400 `invalid_request` because `coord/gem.py:192` passes `model="antigravity-preview-09-2026"` whereas the Interactions API requires `agent="antigravity-preview-09-2026"` for agent IDs.
   - Calling `interactions.create(api_version="v1beta", agent="antigravity-preview-09-2026", environment="remote", ...)` timed out after 60 s (`APITimeoutError`) while provisioning the remote MuJoCo container; per the T27 spec ("do not retry in a loop"), remote container provisioning was not retried.
2. **Antigravity CLI independent test suite (`gemini-4-argon` via `coord/gem.py`):**
   - Receipt `gem-5bfddaf541094b60afa60fcc6eb2139a` (`model_requested="gemini-4-argon"`, `provider_id="v1_ChdkQ0h3YXJTX0o3ZmN4czBQeWRfdDJBSRIXZENId2FyU19KN2ZjeHMwUHlkX3QyQUk"`, `2862` total tokens) generated a standalone `pytest` verification suite from the raw source of `sim/aftershock.py`.
   - Executed in an isolated `uv` environment (`mujoco`, `numpy`, `pytest` on Python 3.11.18): **3/3 tests passed in 4.03 s**.

## 2. Gemini Receipts (`coord/gem.py`)

| Invocation Receipt ID | Key / Model | Outcome | Details |
|---|---|---|---|
| `gem-5d0781c2b711416d9ff4dcb6335ec6a6` | `managed_sandbox` (`antigravity-preview-09-2026`) | `error` (`BadRequestError`) | `coord/gem.py:192` passes `model=` instead of `agent=` for the managed sandbox ID |
| `gem-5bfddaf541094b60afa60fcc6eb2139a` | `lead_reasoning` (`gemini-4-argon`) | `ok` (`2862` tokens) | Generated the independent 3-test `pytest` suite (`output_sha256: 09572252f3e6...`) |

## 3. Independent Verification Suite

```python
import math
import mujoco
import numpy as np
import pytest

from sim import aftershock, scene


@pytest.fixture(scope="module")
def backup_sim():
    m, d = scene.load(scene.BACKUP)
    for _ in range(500):
        mujoco.mj_step(m, d)
    return m, d


def _body_cell(m, d, name):
    bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, name)
    x, y, _ = d.xpos[bid]
    return [math.floor(x / aftershock.RES), math.floor(y / aftershock.RES), 0]


def test_unstable_flags_leaning_pair_and_rejects_route(backup_sim):
    m, d = backup_sim
    unstable, moved = aftershock.unstable_xy(m, d)

    assert set(moved) == {"b10", "b8"}
    assert len(unstable) > 0

    b10_cell = _body_cell(m, d, "b10")
    b8_cell = _body_cell(m, d, "b8")
    assert (b10_cell[0], b10_cell[1]) in unstable
    assert (b8_cell[0], b8_cell[1]) in unstable

    unsafe_route = {
        "id": "route-unsafe-1",
        "cells": [[0, 0, 0], b10_cell, b8_cell],
    }
    res = aftershock.verify(unsafe_route, unstable, moved)

    assert res["id"] == "route-unsafe-1"
    assert res["ok"] is False
    assert b10_cell in res["unstable_cells"]
    assert b8_cell in res["unstable_cells"]
    assert "b10" in res["detail"] and "b8" in res["detail"]


def test_stable_blocks_and_safe_route_accepted(backup_sim):
    m, d = backup_sim
    unstable, moved = aftershock.unstable_xy(m, d)

    all_blocks = {
        aftershock.body_name(m, i) for i in aftershock.candidate_blocks(m)
    }
    stable_blocks = all_blocks - {"b10", "b8"}
    assert len(stable_blocks) > 0
    for b in stable_blocks:
        assert b not in moved

    # Pick cells guaranteed to be outside the unstable set
    max_i = max((i for i, _ in unstable), default=0)
    safe_cells = [[max_i + 10 + step, 0, 0] for step in range(4)]
    for c in safe_cells:
        assert (c[0], c[1]) not in unstable

    safe_route = {"id": "route-safe-1", "cells": safe_cells}
    res = aftershock.verify(safe_route, unstable, moved)

    assert res["id"] == "route-safe-1"
    assert res["ok"] is True
    assert res["unstable_cells"] == []
    assert "none of it on this route" in res["detail"]


def test_determinism_and_no_live_state_mutation(backup_sim):
    m, d = backup_sim
    xpos_before = d.xpos.copy()
    qpos_before = d.qpos.copy()
    mocap_before = d.mocap_pos.copy()

    sample_cell = _body_cell(m, d, "b10")
    route = {"id": "det-route", "cells": [sample_cell, [999, 999, 0]]}

    runs = []
    for _ in range(3):
        unstable, moved = aftershock.unstable_xy(m, d)
        verdict = aftershock.verify(route, unstable, moved)
        runs.append((unstable, moved, verdict))
        np.testing.assert_array_equal(d.xpos, xpos_before)
        np.testing.assert_array_equal(d.qpos, qpos_before)
        np.testing.assert_array_equal(d.mocap_pos, mocap_before)

    u0, m0, v0 = runs[0]
    for u, mv, v in runs[1:]:
        assert u == u0
        assert mv == m0
        assert v == v0
```

## 4. Test Execution Output

```text
============================= test session starts ==============================
platform linux -- Python 3.11.18, pytest-9.2.0, pluggy-1.7.0
collecting ... collected 3 items

test_verify_independent.py::test_unstable_flags_leaning_pair_and_rejects_route PASSED [ 33%]
test_verify_independent.py::test_stable_blocks_and_safe_route_accepted PASSED [ 66%]
test_verify_independent.py::test_determinism_and_no_live_state_mutation PASSED [100%]

============================== 3 passed in 4.03s ===============================
```

## 5. Verification Findings

- **Leaning block failure detection (`PASS`):** In `scene.BACKUP`, `unstable_xy(m, d)` simulates a 3.0 s (`SHAKE = 2.0 s` at `4.0 Hz`, `AMPLITUDE = 0.015 m`, plus `SETTLE = 1.0 s`) ground shake on a cloned `MjData` instance, identifying `b10` and `b8` as exceeding `MOVED = 0.05 m` and rejecting routes intersecting their `MARGIN = 0.10 m` footprint (`ok=False`).
- **Stable block preservation (`PASS`):** All remaining candidate blocks in `scene.BACKUP` displace by `<= 0.05 m`, and routes outside `unstable` return `ok=True` with `unstable_cells=[]`.
- **Determinism and state isolation (`PASS`):** Across 3 consecutive runs, `unstable_xy(m, d)` and `verify()` return identical sets and verdicts while leaving live `d.xpos`, `d.qpos`, and `d.mocap_pos` bitwise unchanged.
- **Note for multi-floor scenes:** `verify()` compares cells on `(i, j)` only (`sim/aftershock.py:10, 106`), which intentionally matches layer `k=0` routes against `k=1` obstacle maps in single-floor scenes; in multi-level scenes (`levels.xml`), `LevelWorld` handles floor-specific routing separately.
