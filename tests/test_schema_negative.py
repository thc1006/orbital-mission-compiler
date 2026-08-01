"""Negative validation tests for mission plan schema.

Tests that invalid plans are rejected at the schema level.
References: ORCHIDE slide 9 (mission plan table format).
"""

import pytest
from pydantic import ValidationError

from orbital_mission_compiler.schemas import (
    MissionEvent,
    MissionEventType,
    AIService,
    WorkflowStep,
    ResourceClass,
)


def _step(**kwargs):
    """Helper: minimal valid WorkflowStep."""
    defaults = {"name": "s", "image": "img:latest", "resource_class": ResourceClass.CPU}
    defaults.update(kwargs)
    return WorkflowStep(**defaults)


def _service(**kwargs):
    """Helper: minimal valid AIService."""
    defaults = {"service_id": "svc", "priority": 1, "steps": [_step()]}
    defaults.update(kwargs)
    return AIService(**defaults)


# ── 1. Non-legal event type ────────────────────────────────────────────


def test_reject_invalid_event_type():
    """Event type must be 'acquisition' or 'download' (slide 9: EV column)."""
    with pytest.raises(ValidationError):
        MissionEvent(timestamp="2029-01-01T00:00:00Z", event_type="launch")


# ── 1b. Timestamp format ────────────────────────────────────────────────


def test_reject_invalid_timestamp_format():
    """MissionEvent timestamp must be a valid RFC3339/ISO datetime with timezone."""
    with pytest.raises(ValidationError):
        MissionEvent(
            timestamp="not-a-datetime",
            event_type=MissionEventType.ACQUISITION,
            instrument="INST_1",
            services=[_service()],
        )


def test_reject_timezone_naive_timestamp():
    """MissionEvent timestamp must include timezone info (AwareDatetime)."""
    with pytest.raises(ValidationError):
        MissionEvent(
            timestamp="2029-01-01T00:00:00",
            event_type=MissionEventType.ACQUISITION,
            instrument="INST_1",
            services=[_service()],
        )


# ── 2. Priority out of bounds ─────────────────────────────────────────


def test_reject_priority_below_zero():
    with pytest.raises(ValidationError):
        _service(priority=-1)


def test_reject_priority_above_100():
    with pytest.raises(ValidationError):
        _service(priority=101)


# ── 3. Acquisition missing instrument ─────────────────────────────────


def test_reject_acquisition_without_instrument():
    """Acquisition events must specify an instrument (slide 9: INST column)."""
    with pytest.raises(ValidationError, match="instrument"):
        MissionEvent(
            timestamp="2029-01-01T00:00:00Z",
            event_type=MissionEventType.ACQUISITION,
            instrument=None,
            services=[_service()],
        )


# ── 4. Download missing required fields ───────────────────────────────


def test_reject_download_without_duration():
    """Download events must specify duration_seconds (slide 9: DT_EV = transmission window)."""
    with pytest.raises(ValidationError, match="duration"):
        MissionEvent(
            timestamp="2029-01-01T00:00:00Z",
            event_type=MissionEventType.DOWNLOAD,
            duration_seconds=None,
            ground_visibility=True,
        )


# ── 5. Visibility / workflow conflicts ────────────────────────────────


def test_reject_download_with_services():
    """Download events must not declare AI services (slide 9: DOWNLOAD rows have no WORKFLOW)."""
    with pytest.raises(ValidationError, match="services"):
        MissionEvent(
            timestamp="2029-01-01T00:00:00Z",
            event_type=MissionEventType.DOWNLOAD,
            duration_seconds=268.0,
            ground_visibility=True,
            services=[_service()],
        )


def test_reject_download_without_visibility():
    """Download requires ground_visibility=True (slide 9: DOWNLOAD rows have VISI=1)."""
    with pytest.raises(ValidationError, match="visibility"):
        MissionEvent(
            timestamp="2029-01-01T00:00:00Z",
            event_type=MissionEventType.DOWNLOAD,
            duration_seconds=268.0,
            ground_visibility=False,
        )


# ── 6. Numeric field constraints ──────────────────────────────────────


def test_reject_negative_orbit():
    """Orbit number must be non-negative."""
    with pytest.raises(ValidationError, match="orbit"):
        MissionEvent(
            timestamp="2029-01-01T00:00:00Z",
            event_type=MissionEventType.ACQUISITION,
            instrument="INST_1",
            orbit=-1,
        )


def test_reject_negative_duration():
    """Duration must be non-negative."""
    with pytest.raises(ValidationError, match="duration"):
        MissionEvent(
            timestamp="2029-01-01T00:00:00Z",
            event_type=MissionEventType.DOWNLOAD,
            duration_seconds=-10.0,
            ground_visibility=True,
        )


def test_reject_empty_mission_id():
    """mission_id must not be empty string (with valid events)."""
    from orbital_mission_compiler.schemas import MissionPlan

    valid_event = MissionEvent(
        timestamp="2029-01-01T00:00:00Z",
        event_type=MissionEventType.DOWNLOAD,
        duration_seconds=100.0,
        ground_visibility=True,
    )
    with pytest.raises(ValidationError, match="mission_id"):
        MissionPlan(mission_id="", events=[valid_event])


def test_reject_empty_events():
    """MissionPlan must have at least one event."""
    from orbital_mission_compiler.schemas import MissionPlan

    with pytest.raises(ValidationError, match="events"):
        MissionPlan(mission_id="test", events=[])


# ── 7. Valid edge cases that should NOT be rejected ───────────────────


def test_accept_valid_acquisition():
    """A well-formed acquisition event must pass validation."""
    event = MissionEvent(
        timestamp="2029-01-01T00:00:00Z",
        event_type=MissionEventType.ACQUISITION,
        instrument="INST_1",
        services=[_service()],
    )
    assert event.instrument == "INST_1"


def test_accept_valid_download():
    """A well-formed download event must pass validation."""
    event = MissionEvent(
        timestamp="2029-01-01T00:00:00Z",
        event_type=MissionEventType.DOWNLOAD,
        duration_seconds=268.0,
        ground_visibility=True,
    )
    assert event.duration_seconds == 268.0

# ── A slash in a node-selector key promises a prefix ────────────────────


def test_node_selector_rejects_empty_prefix():
    """"/foo" leaves an empty prefix behind, the same as "foo" does.

    Only the second is a legal Kubernetes label key, so reading the separator
    back is what tells them apart. Refusing it here is the point of the
    compiler: the alternative is a plan that renders cleanly and is thrown out
    by the API server.
    """
    with pytest.raises(ValidationError):
        _step(preferred_node_selector={"/foo": "v"})


def test_node_selector_still_accepts_a_bare_name_and_a_real_prefix():
    assert _step(preferred_node_selector={"foo": "v"})
    assert _step(preferred_node_selector={"example.com/foo": "v"})


# ── The two flags that gate admission are real booleans ─────────────────


@pytest.mark.parametrize("value", ["yes", "on", "true", 1, "1"])
def test_needs_acceleration_rejects_non_booleans(value):
    """Pydantic reads all of these as true when the field is a plain bool.

    A quoted YAML string would then decide whether a step counts as
    accelerated, which is a mission decision made by a typo.
    """
    with pytest.raises(ValidationError):
        _step(needs_acceleration=value)


@pytest.mark.parametrize("value", ["yes", "on", "true", 1])
def test_ground_visibility_rejects_non_booleans(value):
    with pytest.raises(ValidationError):
        MissionEvent(
            timestamp="2029-10-06T00:23:00Z",
            event_type=MissionEventType.ACQUISITION,
            orbit=1,
            instrument="INST_1",
            ground_visibility=value,
        )


# ── Metadata has to survive the trip to the policy engines ──────────────


def test_metadata_rejects_binary_at_any_depth():
    """Binary validates and then raises while the plan is serialised as JSON.

    That happens after the schema stage and before a verdict, so the caller
    gets a traceback where a structured admission result belongs.
    """
    for value in (
        {"payload": b"\xff\xfe"},
        {"outer": {"inner": b"\xff\xfe"}},
        {"items": [b"\xff\xfe"]},
    ):
        with pytest.raises(ValidationError):
            _step(metadata=value)


def test_metadata_rejects_a_value_that_contains_itself():
    """A YAML alias pointing back at its own container never terminates."""
    loop: dict = {}
    loop["self"] = loop
    with pytest.raises(ValidationError):
        _step(metadata=loop)


def test_metadata_still_accepts_what_json_can_hold():
    """Dates and sets round trip, so the check does not reach for them."""
    import datetime

    assert _step(metadata={"when": datetime.date(2026, 1, 1)})
    assert _step(metadata={"tags": {"a", "b"}})
    assert _step(metadata={"k": "v", "n": 1, "nested": {"l": [1, 2]}})
