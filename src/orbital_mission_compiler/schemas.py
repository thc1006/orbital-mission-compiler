from __future__ import annotations

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


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
    steps: List[WorkflowStep]


class MissionEvent(BaseModel):
    timestamp: str
    event_type: MissionEventType
    instrument: Optional[str] = None
    sensor: Optional[str] = None
    ground_visibility: bool = False
    region_type: Optional[str] = None
    services: List[AIService] = Field(default_factory=list)


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
