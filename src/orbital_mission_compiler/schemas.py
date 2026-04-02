from __future__ import annotations

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, model_validator


class ResourceClass(str, Enum):
    CPU = "cpu"
    GPU = "gpu"
    FPGA = "fpga"


class MissionEventType(str, Enum):
    ACQUISITION = "acquisition"
    DOWNLOAD = "download"


class WorkflowStep(BaseModel):
    name: str
    image: str
    resource_class: ResourceClass = ResourceClass.CPU
    fallback_resource_class: Optional[ResourceClass] = None
    needs_acceleration: bool = False
    command: List[str] = Field(default_factory=list)
    args: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    preferred_node_selector: Dict[str, str] = Field(default_factory=dict)


class AIService(BaseModel):
    service_id: str
    priority: int = Field(ge=0, le=100)
    landscape_type: Optional[str] = None
    steps: List[WorkflowStep] = Field(min_length=1)


class MissionEvent(BaseModel):
    timestamp: str
    event_type: MissionEventType
    orbit: Optional[int] = None
    duration_seconds: Optional[float] = None
    instrument: Optional[str] = None
    sensor: Optional[str] = None
    ground_visibility: bool = False
    region_type: Optional[str] = None
    services: List[AIService] = Field(default_factory=list)

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
    client_id: Optional[str] = None
    events: List[MissionEvent]


class WorkflowIntent(BaseModel):
    mission_id: str
    service_id: str
    priority: int
    workflow_name: str
    steps: List[WorkflowStep]
    resource_hints: Dict[str, Any] = Field(default_factory=dict)
