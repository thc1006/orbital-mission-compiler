from __future__ import annotations

import datetime
import math
import re
from enum import Enum
from typing import Any
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


# Label syntax, per the Kubernetes object-labels reference: a key is an optional
# DNS-subdomain prefix and a name segment, and a value is alphanumeric with
# dashes, underscores and dots inside.
# What a metadata value may be. Dates come out of YAML's safe loader and serialise to
# a stable ISO string, so they stay; everything absent here either has no JSON form or
# reaches JSON as a different value than the plan wrote.
_JSON_METADATA_TYPES = (
    type(None),
    bool,
    int,
    float,
    str,
    list,
    dict,
    datetime.date,
    datetime.datetime,
)

# Metadata is per-step annotation data. Nesting past this, or carrying this many
# values, is not something a mission plan does; the point of the bound is that the
# work is finished or refused on the compiler's terms rather than Python's.
_MAX_METADATA_DEPTH = 32
_MAX_METADATA_NODES = 10_000

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


_PLAIN_DECIMAL_RE = re.compile(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)\Z")


def _plain_decimal(value: Any, field: str) -> Any:
    """Accept a quoted number only when it reads as the number it becomes.

    A string here is coerced by pydantic using Python's own numeric grammar,
    which is wider than what a reader of the plan applies: `'1_0'` becomes ten,
    because Python allows underscores inside a numeric literal, and `'6e2'`
    becomes six hundred. Those are the same "reads one way, loads another"
    ambiguity the strict YAML loader refuses a repeated key for, so they are
    refused here rather than resolved silently.

    `'50'`, `'60.5'`, `' 60 '` and `'+50'` are left alone. They are how a
    templated plan writes a number and there is only one thing they can mean.
    """
    if isinstance(value, str) and not _PLAIN_DECIMAL_RE.fullmatch(value.strip()):
        raise ValueError(
            f"{field} must be a plain decimal number; {value!r} is read by Python as "
            "something a reader of the plan would not read it as"
        )
    return value


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
    timestamp strings and enum values the plan format is written in, and the
    quoted numbers -- ``priority: "50"`` -- that a templated plan is full of.
    Where a loose coercion would change meaning the field carries its own
    validator instead, and there are two such coercions: a boolean read as a
    number, and a quoted number Python's grammar reads differently from a
    reader of the plan (``'1_0'`` is ten, ``'6e2'`` is six hundred).

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
    # Strict: pydantic reads "yes", "on" and 1 as true, so a quoted YAML string
    # would decide whether a step is treated as accelerated.
    needs_acceleration: StrictBool = False
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

    @field_validator("metadata")
    @classmethod
    def _serialisable_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Metadata reaches the policy engines as JSON, so it has to survive the trip.

        YAML's safe loader still builds values JSON has no form for, or values that
        reach JSON as something else. Each is refused here with the reason, because
        the alternative surfaces while the plan is being serialised for a decision
        and the caller gets a traceback where a verdict belongs. Dates round trip to
        a stable string and stay.

        Walked with an explicit stack rather than by recursion: Python's own limit
        depends on how deep the caller already is, so the same plan raised
        RecursionError at one depth from one entry point and survived it from
        another. A bound the compiler sets is one it can report.
        """
        on_path: set[int] = set()
        stack: list[tuple[Any, str, int, bool]] = [(value, "", 0, False)]
        nodes = 0

        while stack:
            node, where, depth, leaving = stack.pop()
            if leaving:
                # Popped once every descendant has been, so a container is only on
                # the path while it is being walked: an anchor used twice side by
                # side is fine and only one reachable from itself is refused.
                on_path.discard(id(node))
                continue

            nodes += 1
            if nodes > _MAX_METADATA_NODES:
                raise ValueError(
                    f"metadata holds more than {_MAX_METADATA_NODES} values"
                )
            if depth > _MAX_METADATA_DEPTH:
                raise ValueError(
                    f"metadata{where} is nested deeper than {_MAX_METADATA_DEPTH}"
                )

            if isinstance(node, bytes | bytearray):
                raise ValueError(f"metadata{where} is binary, which has no JSON form")
            # An unordered collection serialises to an array whose order is not the
            # same twice: the same plan gave nine different orderings across ten
            # interpreter hash seeds. The policy engines are handed this as JSON, so
            # the input the decision is made on, and any digest taken of it, would
            # differ run to run.
            if isinstance(node, set | frozenset):
                raise ValueError(f"metadata{where} is a set, which has no stable JSON order")
            # Serialisation turns these into null, so a plan saying one thing would be
            # judged on another, with nothing recording the substitution.
            if isinstance(node, float) and not math.isfinite(node):
                raise ValueError(f"metadata{where} is {node}, which JSON cannot hold")
            if not isinstance(node, _JSON_METADATA_TYPES):
                raise ValueError(
                    f"metadata{where} is {type(node).__name__}, which is not a JSON value"
                )
            if isinstance(node, dict | list):
                if id(node) in on_path:
                    raise ValueError(f"metadata{where} contains itself")
                on_path.add(id(node))
                stack.append((node, where, depth, True))
                if isinstance(node, dict):
                    for key in node:
                        # The field's own type only constrains the outer mapping;
                        # everything below it sits inside Any. A JSON object keys on
                        # strings, so YAML holding both 1 and "1" arrives as one entry
                        # and the other value is gone -- the policy engines would then
                        # decide on metadata the plan does not contain.
                        if not isinstance(key, str):
                            raise ValueError(
                                f"metadata{where} is keyed by {key!r}, and JSON objects "
                                "key on strings"
                            )
                pairs = node.items() if isinstance(node, dict) else enumerate(node)
                for key, item in pairs:
                    stack.append((item, f"{where}[{key!r}]", depth + 1, False))

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
            prefix, separator, name = key.rpartition("/")
            if not _LABEL_NAME_RE.fullmatch(name or "") or len(name) > 63:
                raise ValueError(f"node selector key {key!r} has an invalid name segment")
            # A key may leave the prefix out, but a slash promises one. Reading the
            # separator back is what tells "foo" apart from "/foo": both leave an
            # empty prefix behind, and only the second is refused by the API server.
            if separator and not prefix:
                raise ValueError(f"node selector key {key!r} has an empty prefix")
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
        """`True` is an int in Python, and YAML reads `yes`/`on`/`true` as one,
        so an unguarded field turns `priority: yes` into 1, the lowest ORCHIDE
        tier and the opposite of what that says."""
        if isinstance(value, bool):
            raise ValueError("priority must be a number between 0 and 100, not a boolean")
        return _plain_decimal(value, "priority")
    execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    steps: list[WorkflowStep] = Field(min_length=1)


class MissionEvent(StrictModel):
    timestamp: AwareDatetime
    event_type: MissionEventType
    orbit: int | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    instrument: str | None = None
    sensor: str | None = None
    # Strict for the same reason as needs_acceleration, and it matters more here:
    # this flag is what a download step is checked against.
    ground_visibility: StrictBool = False
    region_type: str | None = None
    services: list[AIService] = Field(default_factory=list)


    @field_validator("orbit", "duration_seconds", mode="before")
    @classmethod
    def _numbers_are_not_booleans(cls, value: Any, info: Any) -> Any:
        """`orbit: true` is not orbit 1, and `duration_seconds: true` is not a
        one-second acquisition. A boolean here says something the author did not
        mean, and neither reading is worth guessing at."""
        if isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a number, not a boolean")
        return _plain_decimal(value, info.field_name)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _timestamp_is_written_not_counted(cls, value: Any) -> Any:
        """The plan format is RFC 3339 text, which is what the docs promise and
        what every shipped plan uses.

        A number is accepted by default as a Unix timestamp, so `timestamp: 0`
        becomes 1970-01-01 and names an artifact after it, which is never what a
        mission plan meant to say.
        """
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            raise ValueError("timestamp must be an RFC 3339 string, not a number")
        return value

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
    """The compiled intent every renderer reads.

    The renderers are public and callable on their own, so this model is the only
    place that can guarantee they agree. Two of its constraints exist because they
    did not:

    ``steps`` must be non-empty because ``_primary_step`` indexes ``steps[0]`` and
    an empty list surfaced as an ``IndexError`` from inside a renderer rather than
    as a rejected intent.

    ``resource_hints`` must agree with ``steps`` because two renderers read
    different ones. ``render_resource_claim_templates`` decides whether to emit a
    GPU ResourceClaimTemplate from ``resource_hints["requires_gpu"]``, while
    ``render_kueue_job`` decides whether the Job references one from the primary
    step's ``resource_class``. A GPU step with the default empty hints therefore
    produced a Job naming a template nobody emitted -- a Job the scheduler can
    never place. The parser always derived the hints from the steps, so nothing on
    that path changes; what changes is that no other caller can disagree.
    """

    mission_id: str
    service_id: str
    # The same range AIService uses, so an intent cannot be narrower than the plan
    # it was compiled from. Bools are rejected outright: pydantic reads True as 1,
    # which would silently become the lowest usable priority.
    priority: int = Field(ge=0, le=100)
    workflow_name: str
    steps: list[WorkflowStep] = Field(min_length=1)
    resource_hints: dict[str, Any] = Field(default_factory=dict)

    @field_validator("mission_id", "service_id", "workflow_name")
    @classmethod
    def _identifier_not_blank(cls, value: str, info: Any) -> str:
        # Blank rather than empty: each of these names a rendered artifact, and a
        # value of spaces sanitizes to a placeholder instead of failing.
        if not value or not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("priority", mode="before")
    @classmethod
    def _priority_is_not_a_bool(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("priority must be a number, not a boolean")
        return value

    @model_validator(mode="after")
    def _hints_describe_the_steps(self) -> WorkflowIntent:
        derived = {
            "requires_gpu": any(s.resource_class == ResourceClass.GPU for s in self.steps),
            "requires_fpga": any(s.resource_class == ResourceClass.FPGA for s in self.steps),
            "fallback_enabled": any(s.fallback_resource_class is not None for s in self.steps),
        }
        for key, value in derived.items():
            if key not in self.resource_hints:
                # Filled in rather than demanded, so a caller building an intent by
                # hand gets the same artifacts as one that came through the parser.
                self.resource_hints[key] = value
            elif bool(self.resource_hints[key]) is not value:
                raise ValueError(
                    f"resource_hints[{key!r}] is {self.resource_hints[key]!r}, but the "
                    f"steps say {value}; the steps decide, and a renderer reading the "
                    "hint would disagree with one reading the steps"
                )
        return self
