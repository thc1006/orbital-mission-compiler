"""Tests for Kueue Job rendering from WorkflowIntent."""

from orbital_mission_compiler.compiler import (
    load_mission_plan,
    compile_plan_to_intents,
    render_kueue_job,
)
from orbital_mission_compiler.schemas import (
    WorkflowIntent,
    WorkflowStep,
    ResourceClass,
)


def _cpu_only_intent() -> WorkflowIntent:
    """Construct a WorkflowIntent with only CPU steps."""
    return WorkflowIntent(
        mission_id="test-cpu",
        service_id="cpu-svc",
        priority=50,
        workflow_name="test-cpu-svc",
        steps=[
            WorkflowStep(
                name="step-a",
                image="example:latest",
                resource_class=ResourceClass.CPU,
                command=["sh", "-c"],
                args=["echo hello"],
            ),
        ],
        resource_hints={
            "requires_gpu": False,
            "requires_fpga": False,
            "fallback_enabled": False,
        },
    )


def test_render_kueue_job_basic_structure():
    """A CPU-only intent produces a valid Job without GPU resources."""
    intent = _cpu_only_intent()
    job = render_kueue_job(intent, queue_name="orbital-demo-local", namespace="orbital-demo")

    assert job["apiVersion"] == "batch/v1"
    assert job["kind"] == "Job"
    assert job["metadata"]["labels"]["kueue.x-k8s.io/queue-name"] == "orbital-demo-local"
    assert job["metadata"]["labels"]["mission-id"] == "test-cpu"
    assert job["metadata"]["namespace"] == "orbital-demo"

    pod_spec = job["spec"]["template"]["spec"]
    assert pod_spec["restartPolicy"] == "Never"
    assert len(pod_spec["containers"]) == 1

    # CPU-only: no nodeSelector or GPU tolerations
    assert "nodeSelector" not in pod_spec
    assert "tolerations" not in pod_spec
    resources = pod_spec["containers"][0].get("resources", {})
    assert "nvidia.com/gpu" not in resources.get("requests", {})


def test_render_kueue_job_gpu_hints():
    """A plan requiring GPU adds nodeSelector, tolerations, and GPU resource request."""
    plan = load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
    intent = compile_plan_to_intents(plan)[0]
    job = render_kueue_job(intent, queue_name="orbital-demo-local", namespace="orbital-demo")

    pod_spec = job["spec"]["template"]["spec"]

    # GPU intent should have nodeSelector
    assert pod_spec["nodeSelector"]["accelerator"] == "nvidia"

    # GPU intent should have toleration
    tolerations = pod_spec.get("tolerations", [])
    gpu_tol = [t for t in tolerations if t.get("key") == "nvidia.com/gpu"]
    assert len(gpu_tol) == 1

    # GPU resource request
    resources = pod_spec["containers"][0]["resources"]
    assert resources["requests"]["nvidia.com/gpu"] == "1"


def test_render_kueue_job_labels():
    """Job labels include mission-id, service-id, and priority for traceability."""
    plan = load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
    intent = compile_plan_to_intents(plan)[0]
    job = render_kueue_job(intent)

    labels = job["metadata"]["labels"]
    assert labels["mission-id"] == "mission-beta"
    assert labels["service-id"] == "wildfire-detection"
    assert labels["priority"] == "75"
