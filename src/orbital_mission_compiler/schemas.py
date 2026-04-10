from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator


class ResourceClass(str, Enum):
    CPU = "cpu"
    GPU = "gpu"
    FPGA = "fpga"


class MissionEventType(str, Enum):
    ACQUISITION = "acquisition"
    DOWNLOAD = "download"


class StepPhase(str, Enum):
    PREPROCESSING = "preprocessing"
    AI = "ai"
    POSTPROCESSING = "postprocessing"


class ExecutionMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


class WorkflowStep(BaseModel):
    name: str
    image: str
    phase: StepPhase | None = None
    resource_class: ResourceClass = ResourceClass.CPU
    fallback_resource_class: ResourceClass | None = None
    needs_acceleration: bool = False
    command: list[str] = Field(default_factory=list)
    args: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    preferred_node_selector: dict[str, str] = Field(default_factory=dict)


class AIService(BaseModel):
    """AI Service within a mission event (ORCHIDE slide 9: WORKFLOW + PRIORITY).

    Priority uses 0-100 (higher = higher priority). ORCHIDE's onboard system uses
    1-4 (1 = highest). Translation from 0-100 to ORCHIDE's scale belongs in the
    rendering layer, not in the domain model. The compiler preserves priority intent
    as-is; any target-specific mapping is a renderer concern.
    """

    service_id: str
    priority: int = Field(
        ge=0,
        le=100,
        description="0-100 scale; ORCHIDE uses 1-4 (see rendering layer for conversion)",
    )
    landscape_type: str | None = None
    execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    steps: list[WorkflowStep] = Field(min_length=1)


class MissionEvent(BaseModel):
    timestamp: AwareDatetime
    event_type: MissionEventType
    orbit: int | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    instrument: str | None = None
    sensor: str | None = None
    ground_visibility: bool = False
    region_type: str | None = None
    services: list[AIService] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_event_constraints(self) -> "MissionEvent":
        if self.event_type == MissionEventType.ACQUISITION:
            if not self.instrument:
                raise ValueError("acquisition events must specify an instrument (slide 9: INST)")
        if self.event_type == MissionEventType.DOWNLOAD:
            if self.duration_seconds is None:
                raise ValueError(
                    "download events must specify duration_seconds (slide 9: DT_EV transmission window)"
                )
            if self.services:
                raise ValueError(
                    "download events must not declare AI services (slide 9: DOWNLOAD has no WORKFLOW)"
                )
            if not self.ground_visibility:
                raise ValueError(
                    "download events require ground_visibility=true (slide 9: DOWNLOAD VISI=1)"
                )
        return self


class MissionPlan(BaseModel):
    mission_id: str
    client_id: str | None = None
    events: list[MissionEvent] = Field(min_length=1)

    @field_validator("mission_id")
    @classmethod
    def mission_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("mission_id must not be empty")
        return v


class WorkflowIntent(BaseModel):
    mission_id: str
    service_id: str
    priority: int
    workflow_name: str
    steps: list[WorkflowStep]
    resource_hints: dict[str, Any] = Field(default_factory=dict)
