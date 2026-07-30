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


# ── an unknown field is an error, not a silent default ───────────────


def test_a_misspelled_field_is_rejected_rather_than_dropped():
    """Pydantic ignores unknown keys by default, so a typo changes the mission
    instead of failing it.

    `execution_mod: parallel` leaves the service sequential and
    `fallback_resource_clas: cpu` leaves a GPU step with no fallback, and the
    plan is still reported schema-valid. The policy layer cannot recover the
    intent either: what it evaluates is the model dump, from which the
    misspelled key is already gone.
    """
    import pytest as _pytest
    from pydantic import ValidationError

    from orbital_mission_compiler.schemas import AIService, MissionPlan, WorkflowStep

    with _pytest.raises(ValidationError, match="execution_mod"):
        AIService(
            service_id="s", priority=50, execution_mod="parallel",
            steps=[WorkflowStep(name="a", image="i")],
        )
    with _pytest.raises(ValidationError, match="fallback_resource_clas"):
        WorkflowStep(name="a", image="i", fallback_resource_clas="cpu")
    with _pytest.raises(ValidationError, match="commandd"):
        WorkflowStep(name="a", image="i", commandd=["sh"])
    # Every required field present, so the only reason to reject is the unknown
    # one. Spelling it `mission_i` instead would drop `mission_id` and raise for
    # a missing required field whether or not extra fields are forbidden.
    good_event = {
        "timestamp": "2026-08-01T00:00:00Z", "event_type": "acquisition",
        "instrument": "cam", "duration_seconds": 60,
        "services": [{"service_id": "s", "priority": 50,
                      "steps": [{"name": "a", "image": "i"}]}],
    }
    MissionPlan.model_validate({"mission_id": "m", "events": [good_event]})  # baseline
    with _pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        MissionPlan.model_validate(
            {"mission_id": "m", "events": [good_event], "mision_notes": "typo"}
        )
    with _pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        MissionPlan.model_validate(
            {"mission_id": "m", "events": [{**good_event, "instrumnet": "cam"}]}
        )


def test_priority_true_is_not_priority_one():
    """YAML reads `yes`/`on`/`true` as booleans and Python reads `True` as 1, so
    an unguarded field turns `priority: yes` into the lowest ORCHIDE tier."""
    import pytest as _pytest
    from pydantic import ValidationError

    from orbital_mission_compiler.schemas import AIService, WorkflowStep

    with _pytest.raises(ValidationError, match="boolean"):
        AIService(service_id="s", priority=True, steps=[WorkflowStep(name="a", image="i")])
