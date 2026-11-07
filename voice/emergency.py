"""Emergency call preparation module for AFTERSHOCK.

Prepares structured text for emergency calls (999/112) containing the casualty's
location cell/coordinates, detection clues, and estimated vitals (strictly marked simulated).
Publishes 'gate/request' with kind='emergency_call' for human operator approval.
Voice lane prepares the request; it never places the call directly without human authorization.
"""

from __future__ import annotations

from typing import Any


def prepare_emergency_text(casualty: dict[str, Any], cell: list[int] | None = None) -> str:
    """Format emergency report text with simulated vitals clearly marked."""
    c_id = casualty.get("id", "c1")
    pos = casualty.get("pos", [0.0, 0.0, 0.0])
    confidence = casualty.get("confidence", 1.0)
    clues = casualty.get("clues", [])
    clues_str = ", ".join(clues) if clues else "unknown"

    vitals = casualty.get("vitals", {})
    vitals_parts = []
    for k, v in vitals.items():
        if k == "simulated":
            continue
        vitals_parts.append(f"{k}={v} (SIMULATED)")

    vitals_str = ", ".join(vitals_parts) if vitals_parts else "none reported (SIMULATED)"

    loc_str = f"cell {cell}" if cell is not None else f"pos {pos}"

    return (
        f"EMERGENCY CALL: Trapped casualty {c_id} at {loc_str}. "
        f"Detection confidence: {confidence:.2f} via clues: [{clues_str}]. "
        f"Estimated vitals (all simulated): {vitals_str}. "
        f"Human approval required before dispatch."
    )


def prepare_gate_request(
    casualty: dict[str, Any],
    request_id: str | None = None,
    cell: list[int] | None = None,
    route_id: str = "",
) -> dict[str, Any]:
    """Construct a CONTRACT-compliant 'gate/request' message for kind='emergency_call'."""
    cid = casualty.get("id", "c1")
    req_id = request_id or f"g_emerg_{cid}"
    summary = prepare_emergency_text(casualty, cell=cell)

    return {
        "id": req_id,
        "kind": "emergency_call",
        "summary": summary,
        "route": route_id,
    }


async def publish_emergency_request(
    bus: Any,
    casualty: dict[str, Any],
    request_id: str | None = None,
    cell: list[int] | None = None,
    route_id: str = "",
) -> dict[str, Any]:
    """Prepare and publish a gate/request message to the bus for human operator approval."""
    payload = prepare_gate_request(casualty, request_id=request_id, cell=cell, route_id=route_id)
    await bus.publish("gate/request", payload)
    return payload
