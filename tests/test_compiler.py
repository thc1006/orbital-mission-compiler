import logging

import pytest

from orbital_mission_compiler.compiler import load_mission_plan, compile_plan_to_intents, render_argo_workflow
from orbital_mission_compiler.schemas import (
    MissionPlan,
    MissionEvent,
    MissionEventType,
    AIService,
    WorkflowStep,
    WorkflowIntent,
)


def test_unknown_execution_mode_raises():
    """Unknown execution_mode should raise ValueError, not silently default."""
    intent = WorkflowIntent(
        mission_id="test",
        service_id="svc",
        priority=50,
        workflow_name="test-wf",
        steps=[WorkflowStep(name="s1", image="busybox:1.36")],
        resource_hints={"execution_mode": "invalid_mode"},
    )
    with pytest.raises(ValueError, match="Unknown execution_mode"):
        render_argo_workflow(intent)


def test_compile_plan_to_intents():
    plan = load_mission_plan("configs/mission_plans/sample_maritime_surveillance.yaml")
    intents = compile_plan_to_intents(plan)
    assert len(intents) == 1
    assert intents[0].service_id == "maritime-surveillance"
    assert intents[0].resource_hints["requires_gpu"] is True
    assert intents[0].resource_hints["fallback_enabled"] is True


def test_render_argo_workflow():
    plan = load_mission_plan("configs/mission_plans/sample_maritime_surveillance.yaml")
    intent = compile_plan_to_intents(plan)[0]
    wf = render_argo_workflow(intent)
    assert wf["kind"] == "Workflow"
    assert wf["metadata"]["labels"]["service-id"] == "maritime-surveillance"
    detect = [t for t in wf["spec"]["templates"] if t["name"] == "step-1-detect-ships"][0]
    annotations = detect["metadata"]["annotations"]
    assert annotations["fallback-resource-class"] == "cpu"
    assert detect["affinity"]["nodeAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"][0]["weight"] == 100


def test_detect_timeline_conflicts_no_overlap():
    """Non-overlapping events should return empty conflicts."""
    from orbital_mission_compiler.compiler import detect_timeline_conflicts

    plan = MissionPlan(
        mission_id="test-no-overlap",
        events=[
            MissionEvent(
                timestamp="2026-04-15T10:00:00Z",
                event_type=MissionEventType.ACQUISITION,
                instrument="cam",
                duration_seconds=60,
                services=[AIService(
                    service_id="svc1", priority=50,
                    steps=[WorkflowStep(name="s1", image="img:1")],
                )],
            ),
            MissionEvent(
                timestamp="2026-04-15T10:05:00Z",
                event_type=MissionEventType.ACQUISITION,
                instrument="cam",
                duration_seconds=60,
                services=[AIService(
                    service_id="svc2", priority=50,
                    steps=[WorkflowStep(name="s2", image="img:1")],
                )],
            ),
        ],
    )
    conflicts = detect_timeline_conflicts(plan)
    assert conflicts == []


def test_detect_timeline_conflicts_with_overlap():
    """Overlapping acquisition windows should be detected."""
    from orbital_mission_compiler.compiler import detect_timeline_conflicts

    plan = MissionPlan(
        mission_id="test-overlap",
        events=[
            MissionEvent(
                timestamp="2026-04-15T10:00:00Z",
                event_type=MissionEventType.ACQUISITION,
                instrument="cam",
                duration_seconds=120,
                services=[AIService(
                    service_id="svc1", priority=50,
                    steps=[WorkflowStep(name="s1", image="img:1")],
                )],
            ),
            MissionEvent(
                timestamp="2026-04-15T10:01:00Z",
                event_type=MissionEventType.ACQUISITION,
                instrument="cam",
                duration_seconds=120,
                services=[AIService(
                    service_id="svc2", priority=50,
                    steps=[WorkflowStep(name="s2", image="img:1")],
                )],
            ),
        ],
    )
    conflicts = detect_timeline_conflicts(plan)
    assert len(conflicts) == 1
    assert conflicts[0]["overlap_seconds"] == 60.0


def test_compile_with_conflict_check_logs_warning(caplog):
    """compile_plan_to_intents with check_conflicts should log warnings."""
    plan = MissionPlan(
        mission_id="test-warn",
        events=[
            MissionEvent(
                timestamp="2026-04-15T10:00:00Z",
                event_type=MissionEventType.ACQUISITION,
                instrument="cam",
                duration_seconds=120,
                services=[AIService(
                    service_id="svc1", priority=50,
                    steps=[WorkflowStep(name="s1", image="img:1")],
                )],
            ),
            MissionEvent(
                timestamp="2026-04-15T10:01:00Z",
                event_type=MissionEventType.ACQUISITION,
                instrument="cam",
                duration_seconds=120,
                services=[AIService(
                    service_id="svc2", priority=50,
                    steps=[WorkflowStep(name="s2", image="img:1")],
                )],
            ),
        ],
    )
    with caplog.at_level(logging.WARNING, logger="orbital_mission_compiler.compiler"):
        intents = compile_plan_to_intents(plan, check_conflicts=True)
    assert len(intents) == 2  # still compiles
    assert "Timeline conflict" in caplog.text

def test_detect_timeline_conflicts_missing_duration():
    """Events without duration_seconds should be skipped without error."""
    from orbital_mission_compiler.compiler import detect_timeline_conflicts

    plan = MissionPlan(
        mission_id="test-no-duration",
        events=[
            MissionEvent(
                timestamp="2026-04-15T10:00:00Z",
                event_type=MissionEventType.ACQUISITION,
                instrument="cam",
                services=[AIService(
                    service_id="svc1", priority=50,
                    steps=[WorkflowStep(name="s1", image="img:1")],
                )],
            ),
        ],
    )
    conflicts = detect_timeline_conflicts(plan)
    assert conflicts == []


def test_compile_plan_workflow_names_are_unique_when_prefixes_truncate():
    """Long mission/service IDs should not collapse different events into the same workflow name."""
    mission_id = "mission-" + ("x" * 44)
    service_id = "service-" + ("y" * 36)
    step = WorkflowStep(name="s1", image="img:1")

    plan = MissionPlan(
        mission_id=mission_id,
        events=[
            MissionEvent(
                timestamp="2026-04-15T10:00:00Z",
                event_type=MissionEventType.ACQUISITION,
                instrument="cam",
                duration_seconds=60,
                services=[AIService(service_id=service_id, priority=50, steps=[step])],
            ),
            MissionEvent(
                timestamp="2026-04-15T10:00:01Z",
                event_type=MissionEventType.ACQUISITION,
                instrument="cam",
                duration_seconds=60,
                services=[AIService(service_id=service_id, priority=50, steps=[step])],
            ),
        ],
    )
    intents = compile_plan_to_intents(plan)
    names = [i.workflow_name for i in intents]
    assert len(set(names)) == 2
    assert all(len(n) <= 63 for n in names)


def test_render_argo_workflow_disambiguates_duplicate_step_task_names():
    """DAG task names must be unique even when step names sanitize to the same value."""
    intent = WorkflowIntent(
        mission_id="mission-a",
        service_id="svc-a",
        priority=50,
        workflow_name="wf-a",
        steps=[
            WorkflowStep(name="Detect Ships", image="busybox:1.36"),
            WorkflowStep(name="detect_ships", image="busybox:1.36"),
        ],
        resource_hints={"execution_mode": "sequential"},
    )
    wf = render_argo_workflow(intent)
    tasks = wf["spec"]["templates"][0]["dag"]["tasks"]
    task_names = [t["name"] for t in tasks]
    assert len(task_names) == 2
    assert len(set(task_names)) == 2
