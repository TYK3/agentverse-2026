"""Welds that break past a force limit (ref Y1b): how a generated building fails for real.

A scene opts in with two custom numerics, one value per equality constraint in model order:
`weld_limit` (newtons) and `weld_torque_limit` (newton metres). Past either, the weld breaks and is
switched off for good (`d.eq_active[i] = 0`). A limit of 0 means the weld never breaks (the floor plate
weld, robot internals).

`Breaker(m)` is a no-op for scenes without these numerics (backup, tower), so the World and the
aftershock check call it unconditionally.
"""

import mujoco
import numpy as np


def _numeric(m, name):
    k = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_NUMERIC, name)
    if k < 0:
        return None
    adr, size = m.numeric_adr[k], m.numeric_size[k]
    values = np.asarray(m.numeric_data[adr:adr + size], float)
    if len(values) != m.neq:
        raise ValueError(f"{name} has {len(values)} values for {m.neq} equality constraints")
    return values


def weld_loads(m, d):
    """(force norm N, torque norm N m) carried by each equality constraint right now."""
    force, torque = np.zeros(m.neq), np.zeros(m.neq)
    rows = np.flatnonzero(d.efc_type[:d.nefc] == mujoco.mjtConstraint.mjCNSTR_EQUALITY)
    if rows.size == 0:
        return force, torque
    ids, f = d.efc_id[rows], d.efc_force[rows]
    start = 0
    while start < len(rows):                 # a weld's rows are contiguous: 3 force, then 3 torque
        eq, end = int(ids[start]), start
        while end < len(rows) and ids[end] == eq:
            end += 1
        force[eq] = np.linalg.norm(f[start:min(end, start + 3)])
        if end - start >= 6:
            torque[eq] = np.linalg.norm(f[start + 3:start + 6])
        start = end
    return force, torque


class Breaker:
    def __init__(self, m, force=None, torque=None):
        if force is None:
            force, torque = _numeric(m, "weld_limit"), _numeric(m, "weld_torque_limit")
        self.force = force
        self.torque = torque if torque is not None else (None if force is None else np.zeros_like(force))

    @property
    def active(self):
        return self.force is not None

    def step(self, m, d):
        """After mj_step: switch off every breakable weld past its limit. Returns the ids broken now."""
        if self.force is None or d.nefc == 0:
            return []
        f, t = weld_loads(m, d)
        over = ((self.force > 0) & (f > self.force)) | ((self.torque > 0) & (t > self.torque))
        broken = [int(i) for i in np.flatnonzero(over) if d.eq_active[i]]
        for i in broken:
            d.eq_active[i] = 0
        return broken
