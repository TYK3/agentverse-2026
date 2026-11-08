"""PASSAGE-BLOCK-S3: a revoked route that a newer route replaced stops sending the Scout to re-look.

B1 seed 3: r1 was revoked by the dropped block, r2.. were planned around it and granted, but r1 kept
re-sending its re-look every 8 s to a cell in the passage the new route uses, and the Scout parked
there in the Responder's way."""

from planner import permit
from planner.tests.test_permit import elsewhere, gotos, sweep, verified_permits


def test_replaced_revoked_route_stops_relooking():
    ps, _ = verified_permits()
    assert gotos(ps.on_sensors(sweep(hit_at=0.6), 2.0))   # r1 revoked by a shift: one re-look is fine
    ps.on_route_proposed({"id": "r2", "robot": "responder", "cells": [[i, 20, 0] for i in range(10, 30)],
                          "goal": "water", "model": "x"})
    out = ps.on_route_verified({"id": "r2", "ok": True, "unstable_cells": [], "detail": ""}, 3.0)
    assert out[0][1]["granted"] is True
    sent = [g for k in range(40) for g in gotos(ps.on_sensors(elsewhere(), 3.5 + k * 0.5))]
    assert sent == [], sent                                 # r2 is the live route: r1 no longer drives the Scout


def test_newest_revoked_route_still_relooks():
    ps, _ = verified_permits()
    ps.on_sensors(sweep(hit_at=0.6), 2.0)
    sent = [g for k in range(40) for g in gotos(ps.on_sensors(elsewhere(), 2.5 + k * 0.5))]
    assert sent and all("route r1" in g["reason"] for g in sent)
    assert len(sent) <= 20 / permit.RELOOK_EVERY_S + 1
