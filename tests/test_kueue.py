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


def test_kueue_rejects_values_the_api_server_would_reject():
    """Operator-supplied names and quantities are copied into the manifest
    verbatim, so an invalid one has to be caught here.

    Rendering it anyway defers the failure to `kubectl apply`, which is past the
    point this compiler exists to check, and an operator reading a rendered
    manifest has no reason to doubt it.
    """
    intent = WorkflowIntent(
        mission_id="test", service_id="svc", priority=50,
        workflow_name="test-wf",
        steps=[WorkflowStep(name="s1", image="busybox:1.36")],
    )
    for kwargs, field in (
        ({"cpu_request": ""}, "cpu_request"),
        ({"memory_request": "  "}, "memory_request"),
        ({"cpu_request": "one"}, "cpu_request"),
        ({"memory_request": "256 Mi"}, "memory_request"),
        # A character-class approximation of the quantity grammar accepts all
        # of these; resource.ParseQuantity accepts none of them. Checked by
        # running the real parser over them.
        ({"cpu_request": "."}, "cpu_request"),
        ({"cpu_request": "1..2"}, "cpu_request"),
        ({"cpu_request": "1e"}, "cpu_request"),
        ({"cpu_request": "1e+"}, "cpu_request"),
        ({"cpu_request": "1.2.3"}, "cpu_request"),
        ({"cpu_request": "1m1"}, "cpu_request"),
        ({"memory_request": "1K"}, "memory_request"),   # decimal kilo is lowercase
        ({"memory_request": "1mi"}, "memory_request"),
        ({"memory_request": "1i"}, "memory_request"),
        ({"namespace": "Orbital_Demo"}, "namespace"),
        ({"namespace": "-leading-dash"}, "namespace"),
        ({"queue_name": "queue name"}, "queue_name"),
        ({"namespace": "n" * 64}, "namespace"),
    ):
        with pytest.raises(ValueError, match=field):
            render_kueue_job(intent, **kwargs)

    # The shapes an operator actually uses stay accepted.
    for kwargs in (
        {"cpu_request": "500m"}, {"memory_request": "1Gi"}, {"cpu_request": "2"},
        {"cpu_request": "0.5"}, {"cpu_request": "1.5"}, {"cpu_request": "100n"},
        {"memory_request": "1e3"}, {"memory_request": "1Ki"}, {"memory_request": "1k"},
        {"memory_request": "256Mi"}, {"memory_request": ".5Gi"},
        {"namespace": "dra-unified"}, {"queue_name": "orbital-demo-local"},
    ):
        render_kueue_job(intent, **kwargs)


def test_render_kueue_job_labels():
    """Job labels include mission-id, service-id, and priority for traceability."""
    plan = load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
    intent = compile_plan_to_intents(plan)[0]
    job = render_kueue_job(intent)

    labels = job["metadata"]["labels"]
    assert labels["mission-id"] == "mission-beta"
    assert labels["service-id"] == "wildfire-detection"
    assert labels["priority"] == "75"


# ── the Kueue Job is an admission artifact, not the whole service ─────


def test_a_multi_step_service_says_which_steps_are_not_in_the_job():
    """A Kueue Job runs one container, so a three-step service is admitted as
    its primary step only.

    That projection is defensible -- the Argo Workflow is what executes the
    sequence -- but it cannot be silent: the live smoke waits for this Job and
    would otherwise report the service complete when two of its three steps
    never ran.
    """
    plan = load_mission_plan("configs/mission_plans/validation_live_cluster.yaml")
    intent = compile_plan_to_intents(plan)[0]
    assert [s.name for s in intent.steps] == ["preprocess", "detect", "postprocess"]

    job = render_kueue_job(intent)
    containers = job["spec"]["template"]["spec"]["containers"]
    assert len(containers) == 1

    ann = job["metadata"]["annotations"]
    assert ann["orbital/executed-step"] == "preprocess"
    assert ann["orbital/steps-not-in-this-job"] == "detect,postprocess"
    assert ann["orbital/kueue-artifact-role"] == "admission-proxy"


def test_a_single_step_service_reports_nothing_dropped():
    intent = WorkflowIntent(
        mission_id="test", service_id="svc", priority=50, workflow_name="test-wf",
        steps=[WorkflowStep(name="only", image="busybox:1.36")],
    )
    ann = render_kueue_job(intent)["metadata"]["annotations"]
    assert ann["orbital/executed-step"] == "only"
    assert ann["orbital/steps-not-in-this-job"] == ""


def test_service_account_may_be_a_dns_subdomain():
    """A ServiceAccount name is a DNS subdomain, not a label: dots are legal and
    the limit is 253. Verified against a live API server, which accepts
    `workflow.runner` and a 100-character name."""
    from orbital_mission_compiler.compiler import render_argo_workflow

    intent = WorkflowIntent(
        mission_id="test", service_id="svc", priority=50, workflow_name="test-wf",
        steps=[WorkflowStep(name="s1", image="busybox:1.36")],
    )
    for account in ("workflow.runner", "team-a.runtime", "a" * 100):
        wf = render_argo_workflow(intent, namespace="ns", service_account=account)
        assert wf["spec"]["serviceAccountName"] == account
    for bad in ("Workflow.Runner", "-leading", "a..b", "a" * 254):
        with pytest.raises(ValueError, match="service_account"):
            render_argo_workflow(intent, namespace="ns", service_account=bad)


def test_queue_name_may_contain_dots_but_not_exceed_a_label_value():
    """The queue name names a LocalQueue (a subdomain) and is stamped as a label
    value (capped at 63), so the binding constraint is the intersection."""
    intent = WorkflowIntent(
        mission_id="test", service_id="svc", priority=50, workflow_name="test-wf",
        steps=[WorkflowStep(name="s1", image="busybox:1.36")],
    )
    job = render_kueue_job(intent, queue_name="team-a.local")
    assert job["metadata"]["labels"]["kueue.x-k8s.io/queue-name"] == "team-a.local"
    with pytest.raises(ValueError, match="queue_name"):
        render_kueue_job(intent, queue_name="q" * 64)
