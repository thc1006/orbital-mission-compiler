"""Tests for Kueue Job rendering from WorkflowIntent."""

import pytest
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
    """A plan requiring GPU uses DRA by default (resourceClaims, no static nvidia.com/gpu)."""
    plan = load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
    intent = compile_plan_to_intents(plan)[0]
    job = render_kueue_job(intent, queue_name="orbital-demo-local", namespace="orbital-demo")

    pod_spec = job["spec"]["template"]["spec"]

    # DRA path: resourceClaims in pod spec, claims in container resources
    assert "resourceClaims" in pod_spec
    assert len(pod_spec["resourceClaims"]) >= 1
    container = pod_spec["containers"][0]
    assert "claims" in container["resources"]

    # DRA path: no static GPU request, no nodeSelector, no tolerations
    assert "nvidia.com/gpu" not in container["resources"].get("requests", {})
    assert "nodeSelector" not in pod_spec
    assert "tolerations" not in pod_spec


def test_kueue_custom_resource_requests():
    """render_kueue_job should accept custom cpu_request and memory_request."""
    intent = WorkflowIntent(
        mission_id="test", service_id="svc", priority=50,
        workflow_name="test-wf",
        steps=[WorkflowStep(name="s1", image="busybox:1.36")],
    )
    job = render_kueue_job(intent, cpu_request="500m", memory_request="128Mi")
    container = job["spec"]["template"]["spec"]["containers"][0]
    assert container["resources"]["requests"]["cpu"] == "500m"
    assert container["resources"]["requests"]["memory"] == "128Mi"


def test_kueue_default_resources_unchanged():
    """Default cpu/memory should remain 1/256Mi for backward compat."""
    intent = WorkflowIntent(
        mission_id="test", service_id="svc", priority=50,
        workflow_name="test-wf",
        steps=[WorkflowStep(name="s1", image="busybox:1.36")],
    )
    job = render_kueue_job(intent)
    container = job["spec"]["template"]["spec"]["containers"][0]
    assert container["resources"]["requests"]["cpu"] == "1"
    assert container["resources"]["requests"]["memory"] == "256Mi"


def test_kueue_empty_resource_request_raises():
    """Empty cpu_request or memory_request should raise ValueError."""
    intent = WorkflowIntent(
        mission_id="test", service_id="svc", priority=50,
        workflow_name="test-wf",
        steps=[WorkflowStep(name="s1", image="busybox:1.36")],
    )
    with pytest.raises(ValueError, match="cpu_request must not be empty"):
        render_kueue_job(intent, cpu_request="")
    with pytest.raises(ValueError, match="memory_request must not be empty"):
        render_kueue_job(intent, memory_request="  ")


def test_render_kueue_job_labels():
    """Job labels include mission-id, service-id, and priority for traceability."""
    plan = load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
    intent = compile_plan_to_intents(plan)[0]
    job = render_kueue_job(intent)

    labels = job["metadata"]["labels"]
    assert labels["mission-id"] == "mission-beta"
    assert labels["service-id"] == "wildfire-detection"
    assert labels["priority"] == "75"
