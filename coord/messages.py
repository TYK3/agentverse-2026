"""Validated JSON payloads; array topics keep their array wire representation."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

Number = Annotated[float, Field(allow_inf_nan=False)]
Nonnegative = Annotated[Number, Field(ge=0)]
Probability = Annotated[Number, Field(ge=0, le=1)]
Text = Annotated[str, Field(min_length=1)]
Vec3 = Annotated[list[Number], Field(min_length=3, max_length=3)]
Cell = Annotated[list[int], Field(min_length=3, max_length=3)]


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Block(Message):
    id: Text
    label: Text
    pos: Vec3
    size: Annotated[list[Nonnegative], Field(min_length=3, max_length=3)]


class SceneLoaded(Message):
    scene: Literal["backup", "photo", "tower", "building", "levels"]
    blocks: list[Block]


class Pose(Message):
    pos: Vec3
    yaw: Number


class Acoustic(Message):
    bearing: Number
    level: Probability


class CameraFrame(Message):
    format: Literal["jpeg"]
    b64: Text


class ScoutMotion(Message):
    state: Literal["idle", "moving", "arrived", "blocked"]
    target: Annotated[list[Number], Field(min_length=2, max_length=2)] | None


class SensorsScout(Message):
    t: Nonnegative = 0
    pose: Pose
    lidar: list[Nonnegative]
    camera: str | CameraFrame | None = None
    motion: ScoutMotion | None = None
    points: Annotated[list[Vec3], Field(max_length=2048)] | None = None  # depth camera, scene frame (Z1/Y9)
    points_from: Vec3 | None = None  # where the depth camera was for `points`, scene frame (L5)
    thermal: list[list[Probability]]
    acoustic: Acoustic

    @model_validator(mode="after")
    def rectangular_thermal(self):
        if self.thermal and any(len(row) != len(self.thermal[0]) for row in self.thermal):
            raise ValueError("thermal grid must be rectangular")
        return self


class MapCell(Message):
    cell: Cell
    state: Literal["seen", "inferred", "unknown"]
    occupied: bool
    hits: Annotated[int, Field(ge=0)] | None = None


class MapCells(Message):
    t: Nonnegative
    res: Annotated[Number, Field(gt=0)]
    cells: list[MapCell]


class MapPoints(Message):
    t: Nonnegative
    res: Annotated[Number, Field(gt=0)]
    points: Annotated[list[Vec3], Field(max_length=2048)]
    points_from: Vec3 | None = None


class Vitals(Message):
    model_config = ConfigDict(extra="allow", strict=True)
    breathing_rate: Nonnegative
    simulated: Literal[True]


class Casualty(Message):
    id: Text
    pos: Vec3
    confidence: Probability
    clues: list[Literal["pose", "thermal", "sound"]]
    vitals: Vitals


class MapCasualties(RootModel[list[Casualty]]):
    pass


class Hazard(Message):
    cell: Cell
    status: Literal["stable", "at_risk", "collapsed"]
    why: Text
    estimate: Literal[True]
    exclusion: bool | None = None  # keep out: motion was sensed nearby (L5); routes never pass


class MapHazards(RootModel[list[Hazard]]):
    pass


class ScoutGoto(Message):
    target: Vec3
    reason: Text


class ResponderPose(Message):
    """E2: the Responder's actual pose from the sim, every tick (10 Hz), so viewers never snap it to a route end."""
    t: Nonnegative
    pos: Vec3
    yaw: Number
    state: Literal["idle", "moving", "arrived", "blocked", "frozen"]
    route: Text | None = None
    carrying: list[Text]


class RouteProposed(Message):
    id: Text
    robot: Literal["responder"]
    cells: list[Cell]
    goal: Text
    model: Text


class RouteVerified(Message):
    id: Text
    ok: bool
    unstable_cells: list[Cell]
    detail: str


class GateDecision(Message):
    id: Text
    outcome: Literal["act", "relook", "refer"]
    confidence: Probability
    reason: Text


class GateRequest(Message):
    id: Text
    kind: Literal["risky_move", "enter_at_risk", "emergency_call"]
    summary: Text
    route: Text


class GateAnswer(Message):
    id: Text
    approved: bool
    by: Literal["operator"]


class ResponderAction(Message):
    action: Literal["move", "place_supply", "grip", "release"]
    route: Text
    item: Literal["water", "first_aid_kit", "radio", "bandage", "splint", "thermal_blanket"]
    # Y2: a block id (e.g. "b11" to clear, or a found board used as a splint). When set, grip/release
    # act on that block and item names what it is used for; when absent, they act on the kit item.
    block: Text | None = None


class OperatorCommand(Message):
    text: Text
    source: Literal["voice", "typed"]


class WorldChange(Message):
    kind: Literal["aftershock", "block_added"]
    t: Nonnegative
    moved_blocks: list[Text]


Vec2 = Annotated[list[Number], Field(min_length=2, max_length=2)]


class DebrisEvent(Message):
    id: Text
    kind: Literal["moved", "fell", "settled"]
    pos: Vec3
    moved_m: Nonnegative
    drop_m: Nonnegative


class DebrisPile(Message):
    ids: Annotated[list[Text], Field(min_length=1)]
    risk: Probability
    worst: Text
    tilt_deg: Nonnegative
    overhang: Probability
    motion_m: Nonnegative
    top_z: Number
    min_xy: Vec2
    max_xy: Vec2
    unstable: bool


class WorldDebris(Message):
    t: Nonnegative
    truth: Literal[True]
    events: list[DebrisEvent]
    stacks: list[DebrisPile]


class PermitEvidence(Message):
    kind: Literal["verified", "clear", "shift", "hazard", "fresh_scan"]
    detail: Text
    t: Nonnegative


class PermitRoute(Message):
    route: Text
    granted: bool
    t: Nonnegative
    reason: Text
    evidence: list[PermitEvidence]


class LogDecision(Message):
    t: Nonnegative
    perception: str
    model: Text
    physics: str
    outcome: Text
    reason: Text


class StatusLink(Message):
    online: bool


class StatusBudget(Message):
    device: Text
    mem_mb: Nonnegative
    model: Text
    ms_per_step: Nonnegative
    limit: dict[str, Nonnegative]


class StatusGemini(Message):
    mode: Literal["off", "replay", "live"]
    calls_last_hour: Annotated[int, Field(ge=0)]
    stand_ins: list[Text]


TokenCount = Annotated[int, Field(ge=0)]


class GeminiAttempt(Message):
    attempt: Annotated[int, Field(ge=1)]
    sdk_called: bool
    outcome: Literal["ok", "error"]
    error_type: Text | None


class GeminiCacheOrigin(Message):
    id: Text | None
    provider_id: Text | None
    model_requested: Text | None
    model_reported: Text | None
    usage: dict[str, TokenCount] | None


class GeminiReceipt(Message):
    id: Text
    schema_version: Literal[1]
    started_at: Text
    feature: Text
    model_key: Text
    model_requested: Text | None
    model_reported: Text | None
    mode: Literal["off", "replay", "live"]
    source: Literal["none", "disabled", "cache", "live"]
    outcome: Literal["ok", "off", "error", "cap_reached"]
    route: Text | None
    evidence_ids: list[Text]
    provider_id: Text | None
    source_call_id: Text | None
    usage: dict[str, TokenCount] | None
    attempts: list[GeminiAttempt]
    live_attempts: TokenCount
    request_sha256: Text | None
    output_sha256: Text | None
    cache_write_error: Text | None
    elapsed_ms: Nonnegative
    cache_origin: GeminiCacheOrigin | None = None
    error_type: Text | None = None

    @model_validator(mode="after")
    def source_matches_activity(self):
        if self.live_attempts != sum(attempt.sdk_called for attempt in self.attempts):
            raise ValueError("live_attempts must count actual SDK attempts")
        if self.source != "live" and self.live_attempts:
            raise ValueError("non-live sources cannot claim SDK attempts")
        if self.source in ("cache", "disabled") and (self.usage is not None or self.provider_id is not None):
            raise ValueError("cached/disabled calls cannot claim current provider usage or ID")
        if self.source == "disabled" and self.outcome != "off":
            raise ValueError("disabled calls must have an off outcome")
        return self


class Say(Message):
    to: Literal["casualty", "operator"]
    intent: Literal["first_aid", "guide_exit", "reassure"]
    text: Text
    lang: Text


class CasualtyTriage(Message):
    """An accepted supply choice; planner routing and movement gates still apply."""
    id: Text
    injuries: list[Text]
    recommended_action: Literal["water", "first_aid_kit", "radio", "bandage", "splint", "thermal_blanket"]


class CasualtyReply(Message):
    """G3: what one casualty said back (sim persona now, a microphone later), in English."""
    id: Text
    t: Nonnegative
    text: str
    source: Literal["sim", "mic", "typed"]
    level: Probability | None = None


class CasualtyContact(Message):
    """G3: a bounded live dialogue with one casualty; facts are what they said, never a diagnosis."""
    id: Text
    t: Nonnegative
    status: Literal["talking", "done", "unresponsive", "stopped"]
    turns: Annotated[int, Field(ge=0)]
    max_turns: Annotated[int, Field(ge=1)]
    facts: dict[str, bool | None | list[Text]]
    injuries: list[Text]
    receipts: list[Text]


class ReportHandover(Message):
    # Alias avoids shadowing BaseModel.json while preserving the contract.
    report: dict = Field(alias="json")
    markdown: str


class Envelope(Message):
    topic: Text
    data: dict | list


TOPICS: dict[str, type[BaseModel]] = {
    "scene/loaded": SceneLoaded,
    "sensors/scout": SensorsScout,
    "map/cells": MapCells,
    "map/points": MapPoints,
    "map/casualties": MapCasualties,
    "map/hazards": MapHazards,
    "scout/goto": ScoutGoto,
    "route/proposed": RouteProposed,
    "route/verified": RouteVerified,
    "gate/decision": GateDecision,
    "gate/request": GateRequest,
    "gate/answer": GateAnswer,
    "responder/action": ResponderAction,
    "responder/pose": ResponderPose,
    "operator/command": OperatorCommand,
    "world/change": WorldChange,
    "world/debris": WorldDebris,
    "log/decision": LogDecision,
    "permit/route": PermitRoute,
    "status/link": StatusLink,
    "status/budget": StatusBudget,
    "status/gemini": StatusGemini,
    "gemini/receipt": GeminiReceipt,
    "say": Say,
    "casualty/triage": CasualtyTriage,
    "casualty/reply": CasualtyReply,
    "casualty/contact": CasualtyContact,
    "report/handover": ReportHandover,
}


def validate_payload(topic, data):
    """Return JSON-native data, raising before any subscriber sees invalid input."""
    import json

    try:
        schema = TOPICS[topic]
    except KeyError:
        raise ValueError(f"unknown topic: {topic}") from None
    return schema.model_validate_json(json.dumps(data, allow_nan=False), strict=True).model_dump(
        mode="json", by_alias=True, exclude_unset=True
    )
