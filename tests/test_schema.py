"""Tests for ORCHIDE slide 9 schema alignment.

Each test targets a specific field from the ORCHIDE mission plan table (slide 9).
Fields: DATESZ, ORBIT, EV, DT_EV, INST, TYPE, VISI, WORKFLOW, PRIORITY.
"""

from orbital_mission_compiler.schemas import (
    MissionEvent,
    MissionEventType,
    AIService,
    WorkflowStep,
    ResourceClass,
)
from orbital_mission_compiler.compiler import load_mission_plan


# ── Slide 9: ORBIT field ───────────────────────────────────────────────


def test_mission_event_accepts_orbit():
    """MissionEvent should accept an orbit number (slide 9: ORBIT column)."""
    event = MissionEvent(
        timestamp="2029-10-06T00:23:00Z",
        event_type=MissionEventType.ACQUISITION,
        orbit=1,
        instrument="INST_1",
    )
    assert event.orbit == 1


def test_mission_event_orbit_optional():
    """Orbit is optional for backward compatibility with existing plans."""
    event = MissionEvent(
        timestamp="2029-10-06T00:23:00Z",
        event_type=MissionEventType.ACQUISITION,
        instrument="INST_1",
    )
    assert event.orbit is None


# ── Slide 9: DT_EV field ──────────────────────────────────────────────


def test_mission_event_accepts_duration():
    """MissionEvent should accept event duration in seconds (slide 9: DT_EV)."""
    event = MissionEvent(
        timestamp="2029-10-06T00:23:00Z",
        event_type=MissionEventType.ACQUISITION,
        instrument="INST_1",
        duration_seconds=4.0,
    )
    assert event.duration_seconds == 4.0


def test_mission_event_duration_optional():
    """Duration is optional for backward compatibility."""
    event = MissionEvent(
        timestamp="2029-10-06T00:23:00Z",
        event_type=MissionEventType.ACQUISITION,
        instrument="INST_1",
    )
    assert event.duration_seconds is None


# ── Slide 9: TYPE_D1-D4 (per-service landscape type) ──────────────────


def test_ai_service_accepts_landscape_type():
    """AIService should accept landscape_type (slide 9: TYPE per detector)."""
    svc = AIService(
        service_id="maritime-surveillance",
        priority=1,
        landscape_type="ocean",
        steps=[
            WorkflowStep(name="detect", image="example:latest", resource_class=ResourceClass.CPU),
        ],
    )
    assert svc.landscape_type == "ocean"


def test_ai_service_landscape_type_optional():
    """Landscape type is optional for backward compatibility."""
    svc = AIService(
        service_id="test",
        priority=50,
        steps=[
            WorkflowStep(name="step", image="example:latest"),
        ],
    )
    assert svc.landscape_type is None


# ── Full ORCHIDE-format plan loading ──────────────────────────────────


def test_orchide_format_plan_loads():
    """A plan using ORCHIDE slide 9 fields should load and validate."""
    plan = load_mission_plan("configs/mission_plans/sample_orchide_format.yaml")
    assert plan.mission_id == "mission-orchide-demo"

    acq = plan.events[0]
    assert acq.orbit == 1
    assert acq.duration_seconds == 4.0
    assert acq.event_type == MissionEventType.ACQUISITION

    assert len(acq.services) == 2
    assert acq.services[0].landscape_type == "ocean"
    assert acq.services[1].landscape_type == "ocean"


def test_existing_plans_still_load():
    """Existing sample plans must remain valid after schema expansion."""
    plan_a = load_mission_plan("configs/mission_plans/sample_maritime_surveillance.yaml")
    assert plan_a.mission_id == "mission-alpha"
    assert plan_a.events[0].orbit is None
    assert plan_a.events[0].duration_seconds is None

    plan_b = load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
    assert plan_b.mission_id == "mission-beta"
