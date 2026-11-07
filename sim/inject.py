"""The unscripted change (T05): POST /inject on the hub.

    curl -X POST localhost:8000/inject -H "content-type: application/json" \
         -d '{"kind":"block_added","pos":[0.6,0.25,0.1]}'
    curl -X POST localhost:8000/inject -H "content-type: application/json" -d '{"kind":"aftershock"}'

block_added drops the spare rubble block at pos; aftershock starts the live shake. Either way the
sim loop publishes world/change once the world has the change. The route is added to the hub's
FastAPI app only when coord.hub is already loaded, so tests and scripts never import FastAPI.
"""

import sys


def handle(world, body):
    """Apply one inject request to the world. Returns (status code, response body)."""
    kind = body.get("kind") if isinstance(body, dict) else None
    if kind == "block_added":
        pos = body.get("pos")
        if not (isinstance(pos, list) and len(pos) == 3 and all(isinstance(v, (int, float)) for v in pos)):
            return 400, {"error": "block_added needs pos [x, y, z]"}
        name = world.add_block(pos)
        if name is None:
            return 409, {"error": "no spare block left"}
        return 200, {"ok": True, "block": name}
    if kind == "aftershock":
        if not world.trigger_aftershock():
            return 409, {"error": "an aftershock is already running"}
        return 200, {"ok": True}
    return 400, {"error": "kind must be block_added or aftershock"}


def install(world):
    """Add POST /inject to the hub app when running inside the hub. Returns True if added."""
    hub = sys.modules.get("coord.hub")
    app = getattr(hub, "app", None)
    if app is None:
        return False
    from fastapi import Request
    from fastapi.responses import JSONResponse

    async def inject(request: Request):
        status, body = handle(world, await request.json())
        return JSONResponse(body, status_code=status)

    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/inject"]
    app.add_api_route("/inject", inject, methods=["POST"])
    return True
