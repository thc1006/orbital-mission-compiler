from __future__ import annotations

import re
from enum import Enum
from typing import Any
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


# Label syntax, per the Kubernetes object-labels reference: a key is an optional
# DNS-subdomain prefix and a name segment, and a value is alphanumeric with
# dashes, underscores and dots inside.
_DNS_LABEL_RE = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?\Z")
_LABEL_NAME_RE = re.compile(r"[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?\Z")
_LABEL_VALUE_RE = re.compile(r"[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?\Z")


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


class StrictModel(BaseModel):
    """Base for every mission-plan model: an unknown field is an error.

    Pydantic ignores unrecognised keys by default, which for an admission schema
    means a typo changes the mission rather than failing it. ``execution_mod:
    parallel`` leaves the service sequential, ``fallback_resource_clas: cpu``
    leaves an accelerator step with no fallback, and the plan is still reported
    as schema-valid. The policy layer cannot recover the intent either, because
    what it evaluates is the model dump, from which the misspelled key is
    already gone.

    ``strict`` is deliberately not set here: it would reject the RFC 3339
    timestamp strings and enum values the plan format is written in. Where a
    loose coercion would actually change meaning -- a boolean read as a
    number -- the field carries its own validator.

    ``allow_inf_nan`` is off. YAML spells infinity ``.inf`` and Pydantic accepts
    it for a float by default, and ``duration_seconds: .inf`` passes ``ge=0``.
    It then reaches the timeline analysis, where ``start + duration`` swallows
    every later event: a plan with one infinite acquisition reports a conflict
    with an event five months away and puts a plausible-looking number on it.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class WorkflowStep(StrictModel):
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

    @field_validator("name", "image")
    @classmethod
    def _not_blank(cls, value: str, info: Any) -> str:
        """A step with no image is not something that can run.

        Blank rather than merely empty: a name of spaces sanitizes to a
        placeholder and an image of spaces reaches the API server as-is.
        """
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("preferred_node_selector")
    @classmethod
    def _valid_label_selector(cls, value: dict[str, str]) -> dict[str, str]:
        """Node-selector keys and values are copied into a label selector.

        Validated here rather than at apply time, which is the whole point of
        this compiler: a malformed qualified key or an over-long value renders
        cleanly and is refused by the API server.
        """
        for key, val in value.items():
            prefix, _, name = key.rpartition("/")
            if not _LABEL_NAME_RE.fullmatch(name or "") or len(name) > 63:
                raise ValueError(f"node selector key {key!r} has an invalid name segment")
            # Each segment is a DNS label in its own right, so the 63-character
            # limit applies per segment as well as 253 to the whole prefix.
            parts = prefix.split(".") if prefix else []
            if prefix and (
                len(prefix) > 253
                or not all(_DNS_LABEL_RE.fullmatch(part) and len(part) <= 63 for part in parts)
            ):
                raise ValueError(f"node selector key {key!r} has an invalid prefix")
            if val and (len(val) > 63 or not _LABEL_VALUE_RE.fullmatch(val)):
                raise ValueError(f"node selector value {val!r} for {key!r} is not a label value")
        return value


class AIService(StrictModel):
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

    @field_validator("service_id")
    @classmethod
    def _service_id_not_blank(cls, value: str) -> str:
        """A service id names the workflow and the file it is written to."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError("service_id must not be blank")
        return value

    @field_validator("priority", mode="before")
    @classmethod
    def _priority_is_not_a_boolean(cls, value: Any) -> Any:
        """`True` is an int in Python, and YAML reads `yes`/`on`/`true` as one.

        Accepting it silently turns a mission priority into 1, the lowest ORCHIDE
        tier, which is the opposite of what someone writing `priority: yes`
        intends. There is no reading of a boolean as a 0-100 priority worth
        guessing at.
        """
        if isinstance(value, bool):
            raise ValueError("priority must be a number between 0 and 100, not a boolean")
        return value
    execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    steps: list[WorkflowStep] = Field(min_length=1)


class MissionEvent(StrictModel):
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
            if not self.instrument or not self.instrument.strip():
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


class MissionPlan(StrictModel):
    mission_id: str
    client_id: str | None = None
    events: list[MissionEvent] = Field(min_length=1)

    @field_validator("mission_id")
    @classmethod
    def mission_id_not_empty(cls, v: str) -> str:
        # Blank, not merely empty: the id names every rendered artifact, and a
        # value of spaces sanitizes to a placeholder rather than failing.
        if not v or not v.strip():
            raise ValueError("mission_id must not be blank")
        return v


class WorkflowIntent(StrictModel):
    mission_id: str
    service_id: str
    priority: int
    workflow_name: str
    steps: list[WorkflowStep]
    resource_hints: dict[str, Any] = Field(default_factory=dict)
