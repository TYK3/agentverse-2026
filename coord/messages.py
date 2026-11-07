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
    scene: Literal["backup", "photo"]
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


class MapHazards(RootModel[list[Hazard]]):
    pass


class ScoutGoto(Message):
    target: Vec3
    reason: Text


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


class Say(Message):
    to: Literal["casualty", "operator"]
    intent: Literal["first_aid", "guide_exit", "reassure"]
    text: Text
    lang: Text


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
    "map/casualties": MapCasualties,
    "map/hazards": MapHazards,
    "scout/goto": ScoutGoto,
    "route/proposed": RouteProposed,
    "route/verified": RouteVerified,
    "gate/decision": GateDecision,
    "gate/request": GateRequest,
    "gate/answer": GateAnswer,
    "responder/action": ResponderAction,
    "operator/command": OperatorCommand,
    "world/change": WorldChange,
    "world/debris": WorldDebris,
    "log/decision": LogDecision,
    "status/link": StatusLink,
    "status/budget": StatusBudget,
    "status/gemini": StatusGemini,
    "say": Say,
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
