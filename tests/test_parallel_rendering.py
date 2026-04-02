"""Tests for parallel execution mode DAG rendering.

ORCHIDE slide 10: AI Services can be "configured to be launched sequentially
or in parallel." Currently render_argo_workflow always produces sequential DAGs.
These tests verify parallel mode produces fan-out DAGs.
"""

from orbital_mission_compiler.compiler import (
    compile_plan_to_intents,
    load_mission_plan,
    render_argo_workflow,
)
from orbital_mission_compiler.schemas import (
    AIService,
    ExecutionMode,
    MissionEvent,
    MissionEventType,
    MissionPlan,
    ResourceClass,
    StepPhase,
    WorkflowStep,
)


def _make_intent(execution_mode: ExecutionMode):
    """Build a WorkflowIntent with 3 steps and given execution_mode."""
    plan = MissionPlan(
        mission_id="test",
        events=[
            MissionEvent(
                timestamp="2029-01-01T00:00:00Z",
                event_type=MissionEventType.ACQUISITION,
                instrument="INST_1",
                services=[
                    AIService(
                        service_id="svc",
                        priority=1,
                        execution_mode=execution_mode,
                        steps=[
                            WorkflowStep(
                                name="preprocess",
                                image="img:latest",
                                phase=StepPhase.PREPROCESSING,
                            ),
                            WorkflowStep(
                                name="detect",
                                image="img:latest",
                                phase=StepPhase.AI,
                                resource_class=ResourceClass.GPU,
                                fallback_resource_class=ResourceClass.CPU,
                                needs_acceleration=True,
                            ),
                            WorkflowStep(
                                name="postprocess",
                                image="img:latest",
                                phase=StepPhase.POSTPROCESSING,
                            ),
                        ],
                    )
                ],
            )
        ],
    )
    return compile_plan_to_intents(plan)[0]


# ── Sequential (existing behavior, regression test) ──────────────────


def _get_dag_tasks(wf):
    """Find the 'main' template's DAG tasks by name (not index)."""
    for tmpl in wf["spec"]["templates"]:
        if tmpl["name"] == "main":
            return tmpl["dag"]["tasks"]
    raise ValueError("No 'main' template found")


def test_sequential_dag_has_linear_dependencies():
    """Sequential mode: each step depends on previous (A→B→C)."""
    intent = _make_intent(ExecutionMode.SEQUENTIAL)
    wf = render_argo_workflow(intent)
    dag_tasks = _get_dag_tasks(wf)

    assert len(dag_tasks) == 3
    assert "depends" not in dag_tasks[0]  # first has no deps
    assert dag_tasks[1].get("depends") is not None  # second depends on first
    assert dag_tasks[2].get("depends") is not None  # third depends on second


# ── Parallel (new behavior) ──────────────────────────────────────────


def test_parallel_dag_has_no_dependencies():
    """Parallel mode: all steps run simultaneously (no depends)."""
    intent = _make_intent(ExecutionMode.PARALLEL)
    wf = render_argo_workflow(intent)
    dag_tasks = _get_dag_tasks(wf)

    assert len(dag_tasks) == 3
    for task in dag_tasks:
        assert "depends" not in task, f"Task {task['name']} should have no depends in parallel mode"


def test_parallel_dag_passes_argo_lint_structure():
    """Parallel DAG should still produce valid Argo Workflow structure."""
    intent = _make_intent(ExecutionMode.PARALLEL)
    wf = render_argo_workflow(intent)
    assert wf["apiVersion"] == "argoproj.io/v1alpha1"
    assert wf["kind"] == "Workflow"
    assert wf["spec"]["entrypoint"] == "main"


# ── Execution mode reflected in annotations ──────────────────────────


def test_execution_mode_in_workflow_annotations():
    """Workflow annotations should include the execution_mode."""
    for mode in [ExecutionMode.SEQUENTIAL, ExecutionMode.PARALLEL]:
        intent = _make_intent(mode)
        wf = render_argo_workflow(intent)
        annotations = wf["metadata"].get("annotations", {})
        assert annotations.get("orbital/execution-mode") == mode.value


# ── ORCHIDE format plan with phases ──────────────────────────────────


def test_orchide_plan_sequential_by_default():
    """ORCHIDE sample plan defaults to sequential — regression check."""
    intents = compile_plan_to_intents(
        load_mission_plan("configs/mission_plans/sample_orchide_format.yaml")
    )
    wf = render_argo_workflow(intents[0])
    dag_tasks = _get_dag_tasks(wf)
    # Default is sequential: tasks 1,2 should have depends
    assert dag_tasks[1].get("depends") is not None
