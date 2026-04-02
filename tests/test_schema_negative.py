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


# ── 6. Valid edge cases that should NOT be rejected ───────────────────


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
