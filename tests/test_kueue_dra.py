"""Tests for Kueue DRA (Dynamic Resource Allocation) rendering.

Validates that render_kueue_job and render_resource_claim_templates
produce correct DRA-aware output for GPU, FPGA, and CPU workloads.

Issue #46: Kueue DRA rendering for heterogeneous accelerators.
Reference: ORCHIDE slide 14 (heterogeneous hardware), Kueue v0.17 DRA docs.
"""


from orbital_mission_compiler.compiler import (
    render_kueue_job,
    render_resource_claim_templates,
)
from orbital_mission_compiler.schemas import (
    ResourceClass,
    WorkflowIntent,
    WorkflowStep,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


def _gpu_intent() -> WorkflowIntent:
    return WorkflowIntent(
        mission_id="test-gpu",
        service_id="gpu-svc",
        priority=75,
        workflow_name="test-gpu-svc",
        steps=[
            WorkflowStep(
                name="preprocess",
                image="busybox:1.36",
                resource_class=ResourceClass.CPU,
            ),
            WorkflowStep(
                name="detect",
                image="nvcr.io/nvidia/pytorch:24.01-py3",
                resource_class=ResourceClass.GPU,
                fallback_resource_class=ResourceClass.CPU,
                needs_acceleration=True,
            ),
        ],
        resource_hints={
            "requires_gpu": True,
            "requires_fpga": False,
            "fallback_enabled": True,
        },
    )


def _fpga_intent() -> WorkflowIntent:
    return WorkflowIntent(
        mission_id="test-fpga",
        service_id="fpga-svc",
        priority=60,
        workflow_name="test-fpga-svc",
        steps=[
            WorkflowStep(
                name="signal-proc",
                image="xilinx/signal:latest",
                resource_class=ResourceClass.FPGA,
                needs_acceleration=True,
            ),
        ],
        resource_hints={
            "requires_gpu": False,
            "requires_fpga": True,
            "fallback_enabled": False,
        },
    )


def _cpu_intent() -> WorkflowIntent:
    return WorkflowIntent(
        mission_id="test-cpu",
        service_id="cpu-svc",
        priority=50,
        workflow_name="test-cpu-svc",
        steps=[
            WorkflowStep(
                name="step-a",
                image="busybox:1.36",
                resource_class=ResourceClass.CPU,
            ),
        ],
        resource_hints={
            "requires_gpu": False,
            "requires_fpga": False,
            "fallback_enabled": False,
        },
    )


# ── GPU + DRA (default) ─────────────────────────────────────────────────


class TestGpuDra:
    """GPU intents with DRA enabled (default) use ResourceClaims instead of static requests."""

    def test_gpu_job_has_resource_claims_in_pod_spec(self):
        job = render_kueue_job(_gpu_intent())
        pod_spec = job["spec"]["template"]["spec"]
        assert "resourceClaims" in pod_spec, "DRA-enabled GPU Job must have pod.spec.resourceClaims"

    def test_gpu_job_resource_claim_references_template(self):
        job = render_kueue_job(_gpu_intent())
        claims = job["spec"]["template"]["spec"]["resourceClaims"]
        assert len(claims) >= 1
        claim = claims[0]
        assert "resourceClaimTemplateName" in claim, (
            "resourceClaim must reference a ResourceClaimTemplate"
        )

    def test_gpu_container_has_resource_claims(self):
        job = render_kueue_job(_gpu_intent())
        container = job["spec"]["template"]["spec"]["containers"][0]
        assert "claims" in container.get("resources", {}), (
            "DRA-enabled GPU container must have resources.claims"
        )

    def test_gpu_job_no_static_gpu_request(self):
        """DRA-enabled GPU Job should NOT have nvidia.com/gpu in resource requests."""
        job = render_kueue_job(_gpu_intent())
        resources = job["spec"]["template"]["spec"]["containers"][0]["resources"]
        assert "nvidia.com/gpu" not in resources.get("requests", {}), (
            "DRA replaces static nvidia.com/gpu requests"
        )

    def test_gpu_job_no_node_selector(self):
        """DRA handles device placement — no nodeSelector needed."""
        job = render_kueue_job(_gpu_intent())
        pod_spec = job["spec"]["template"]["spec"]
        assert "nodeSelector" not in pod_spec

    def test_gpu_job_no_tolerations(self):
        """DRA handles device placement — no tolerations needed."""
        job = render_kueue_job(_gpu_intent())
        pod_spec = job["spec"]["template"]["spec"]
        assert "tolerations" not in pod_spec

    def test_gpu_job_still_has_cpu_memory_requests(self):
        job = render_kueue_job(_gpu_intent())
        resources = job["spec"]["template"]["spec"]["containers"][0]["resources"]
        assert resources["requests"]["cpu"] == "1"
        assert resources["requests"]["memory"] == "256Mi"


# ── GPU + DRA disabled (backward compat) ─────────────────────────────────


class TestGpuLegacy:
    """GPU intents with dra_enabled=False use old static nvidia.com/gpu behavior."""

    def test_legacy_gpu_has_static_request(self):
        job = render_kueue_job(_gpu_intent(), dra_enabled=False)
        resources = job["spec"]["template"]["spec"]["containers"][0]["resources"]
        assert resources["requests"]["nvidia.com/gpu"] == "1"

    def test_legacy_gpu_has_node_selector(self):
        job = render_kueue_job(_gpu_intent(), dra_enabled=False)
        pod_spec = job["spec"]["template"]["spec"]
        assert pod_spec["nodeSelector"]["accelerator"] == "nvidia"

    def test_legacy_gpu_has_tolerations(self):
        job = render_kueue_job(_gpu_intent(), dra_enabled=False)
        tolerations = job["spec"]["template"]["spec"].get("tolerations", [])
        gpu_tol = [t for t in tolerations if t.get("key") == "nvidia.com/gpu"]
        assert len(gpu_tol) == 1

    def test_legacy_gpu_no_resource_claims(self):
        job = render_kueue_job(_gpu_intent(), dra_enabled=False)
        pod_spec = job["spec"]["template"]["spec"]
        assert "resourceClaims" not in pod_spec


# ── FPGA (legacy extended resource, no DRA driver) ───────────────────────


class TestFpga:
    """FPGA intents use legacy extended resource (no DRA driver available)."""

    def test_fpga_job_has_fpga_resource_request(self):
        job = render_kueue_job(_fpga_intent())
        resources = job["spec"]["template"]["spec"]["containers"][0]["resources"]
        assert resources["requests"].get("xilinx.com/fpga") == "1"

    def test_fpga_job_has_fpga_limits(self):
        job = render_kueue_job(_fpga_intent())
        resources = job["spec"]["template"]["spec"]["containers"][0]["resources"]
        assert resources["limits"]["xilinx.com/fpga"] == "1"

    def test_fpga_job_has_node_selector(self):
        job = render_kueue_job(_fpga_intent())
        pod_spec = job["spec"]["template"]["spec"]
        assert pod_spec["nodeSelector"]["accelerator"] == "fpga"

    def test_fpga_job_has_tolerations(self):
        job = render_kueue_job(_fpga_intent())
        tolerations = job["spec"]["template"]["spec"].get("tolerations", [])
        fpga_tol = [t for t in tolerations if t.get("key") == "xilinx.com/fpga"]
        assert len(fpga_tol) == 1

    def test_fpga_job_no_resource_claims(self):
        """FPGA has no DRA driver — should not produce resourceClaims."""
        job = render_kueue_job(_fpga_intent())
        pod_spec = job["spec"]["template"]["spec"]
        assert "resourceClaims" not in pod_spec

    def test_fpga_annotation_present(self):
        job = render_kueue_job(_fpga_intent())
        annotations = job["metadata"]["annotations"]
        assert annotations["orbital/requires-fpga"] == "true"


# ── Mixed GPU+FPGA (edge case) ───────────────────────────────────────────


def _gpu_fpga_intent() -> WorkflowIntent:
    """Intent with both GPU and FPGA steps (unlikely but defensible)."""
    return WorkflowIntent(
        mission_id="test-mixed",
        service_id="mixed-svc",
        priority=80,
        workflow_name="test-mixed-svc",
        steps=[
            WorkflowStep(name="gpu-step", image="gpu:latest", resource_class=ResourceClass.GPU),
            WorkflowStep(name="fpga-step", image="fpga:latest", resource_class=ResourceClass.FPGA),
        ],
        resource_hints={"requires_gpu": True, "requires_fpga": True, "fallback_enabled": False},
    )


class TestMixedGpuFpga:
    """A service mixing GPU and FPGA steps is legal, and the Job says which it ran.

    One Pod asking for both devices would be unschedulable, which is what this
    used to reject. But the Kueue Job carries one container from one step, so it
    only ever has one resource class: the mixture is a property of the service,
    which Argo renders as separate Pods. Rejecting it here refused a valid plan
    on the strength of steps that this artifact does not contain.
    """

    def test_mixed_service_renders_the_primary_step_only(self):
        job = render_kueue_job(_gpu_fpga_intent())
        containers = job["spec"]["template"]["spec"]["containers"]
        assert len(containers) == 1
        ann = job["metadata"]["annotations"]
        assert ann["orbital/executed-step-resource-class"] == "gpu"
        assert ann["orbital/requires-gpu"] == "true"
        assert ann["orbital/requires-fpga"] == "false", (
            "the Job does not run the FPGA step, so it must not claim to need one"
        )

    def test_the_service_wide_mixture_is_still_recorded(self):
        ann = render_kueue_job(_gpu_fpga_intent())["metadata"]["annotations"]
        assert ann["orbital/service-requires-gpu"] == "true"
        assert ann["orbital/service-requires-fpga"] == "true"
        assert "fpga" in ann["orbital/steps-not-in-this-job"]


# ── CPU (unchanged) ──────────────────────────────────────────────────────


class TestCpuUnchanged:
    """CPU-only intents are unchanged by DRA support."""

    def test_cpu_no_resource_claims(self):
        job = render_kueue_job(_cpu_intent())
        pod_spec = job["spec"]["template"]["spec"]
        assert "resourceClaims" not in pod_spec

    def test_cpu_no_accelerator_resources(self):
        job = render_kueue_job(_cpu_intent())
        resources = job["spec"]["template"]["spec"]["containers"][0]["resources"]
        requests = resources.get("requests", {})
        assert "nvidia.com/gpu" not in requests
        assert "xilinx.com/fpga" not in requests

    def test_cpu_no_node_selector(self):
        job = render_kueue_job(_cpu_intent())
        pod_spec = job["spec"]["template"]["spec"]
        assert "nodeSelector" not in pod_spec


# ── ResourceClaimTemplate rendering ──────────────────────────────────────


class TestResourceClaimTemplates:
    """render_resource_claim_templates produces correct DRA resources."""

    def test_gpu_intent_produces_one_template(self):
        templates = render_resource_claim_templates(_gpu_intent(), namespace="test-ns")
        assert len(templates) == 1

    def test_gpu_template_api_version(self):
        templates = render_resource_claim_templates(_gpu_intent(), namespace="test-ns")
        assert templates[0]["apiVersion"] == "resource.k8s.io/v1"

    def test_gpu_template_kind(self):
        templates = render_resource_claim_templates(_gpu_intent(), namespace="test-ns")
        assert templates[0]["kind"] == "ResourceClaimTemplate"

    def test_gpu_template_device_class(self):
        templates = render_resource_claim_templates(_gpu_intent(), namespace="test-ns")
        rct = templates[0]
        requests = rct["spec"]["spec"]["devices"]["requests"]
        assert len(requests) >= 1
        assert requests[0]["exactly"]["deviceClassName"] == "gpu.nvidia.com"

    def test_gpu_template_namespace(self):
        templates = render_resource_claim_templates(_gpu_intent(), namespace="orbital-demo")
        assert templates[0]["metadata"]["namespace"] == "orbital-demo"

    def test_gpu_template_name_contains_workflow(self):
        templates = render_resource_claim_templates(_gpu_intent(), namespace="test-ns")
        name = templates[0]["metadata"]["name"]
        assert "test-gpu-svc" in name

    def test_cpu_intent_produces_no_templates(self):
        templates = render_resource_claim_templates(_cpu_intent(), namespace="test-ns")
        assert templates == []

    def test_fpga_intent_produces_no_templates(self):
        """No FPGA DRA driver exists — no ResourceClaimTemplates generated."""
        templates = render_resource_claim_templates(_fpga_intent(), namespace="test-ns")
        assert templates == []


# ── Job ↔ Template cross-reference ───────────────────────────────────────


class TestJobTemplateLink:
    """The Job's resourceClaim must reference the generated template name."""

    def test_job_references_generated_template_name(self):
        intent = _gpu_intent()
        templates = render_resource_claim_templates(intent, namespace="test-ns")
        job = render_kueue_job(intent)

        template_name = templates[0]["metadata"]["name"]
        pod_claims = job["spec"]["template"]["spec"]["resourceClaims"]
        referenced_names = [c["resourceClaimTemplateName"] for c in pod_claims]
        assert template_name in referenced_names, (
            f"Job must reference template {template_name!r}, got {referenced_names}"
        )


# ── firstAvailable DRA fallback (opt-in) ─────────────────────────────────


class TestFirstAvailable:
    """Opt-in dra_fallback renders a scheduler-level firstAvailable claim.

    The default (flag off) path is unchanged; these tests pin the opt-in shape
    and its guard conditions (driver-backed classes only, FPGA excluded).
    """

    def _req(self, intent, **kw):
        templates = render_resource_claim_templates(intent, namespace="test-ns", **kw)
        # dra_fallback on a GPU step yields TWO templates: the scheduler-route
        # firstAvailable claim and the Kueue-route exactly claim. Return the
        # firstAvailable request when present, else the sole template's request.
        for t in templates:
            req = t["spec"]["spec"]["devices"]["requests"][0]
            if "firstAvailable" in req:
                return req
        return templates[0]["spec"]["spec"]["devices"]["requests"][0]

    def test_fallback_produces_first_available_not_exactly(self):
        req = self._req(_gpu_intent(), dra_fallback=True)
        assert "firstAvailable" in req
        assert "exactly" not in req

    def test_fallback_prefers_gpu_then_cpu(self):
        req = self._req(_gpu_intent(), dra_fallback=True)
        classes = [s["deviceClassName"] for s in req["firstAvailable"]]
        assert classes == ["gpu.nvidia.com", "dra.cpu"]

    def test_fallback_subrequest_names_present_and_distinct(self):
        req = self._req(_gpu_intent(), dra_fallback=True)
        names = [s["name"] for s in req["firstAvailable"]]
        assert all(names)
        assert len(set(names)) == len(names)

    def test_fallback_template_api_and_kind(self):
        templates = render_resource_claim_templates(
            _gpu_intent(), namespace="test-ns", dra_fallback=True
        )
        assert templates[0]["apiVersion"] == "resource.k8s.io/v1"
        assert templates[0]["kind"] == "ResourceClaimTemplate"

    def test_default_off_keeps_exactly(self):
        """Regression guard: flag defaults off -> unchanged exactly GPU claim."""
        req = self._req(_gpu_intent())
        assert req["exactly"]["deviceClassName"] == "gpu.nvidia.com"
        assert "firstAvailable" not in req

    def test_gpu_without_fallback_falls_back_to_exactly(self):
        """dra_fallback on, but the accelerator step declares no fallback."""
        intent = _gpu_intent()
        intent.steps[1].fallback_resource_class = None
        req = self._req(intent, dra_fallback=True)
        assert "exactly" in req
        assert "firstAvailable" not in req

    def test_fpga_fallback_fabricates_no_claim(self):
        """FPGA has no DRA driver: dra_fallback must not invent a claim for it."""
        intent = _fpga_intent()
        intent.steps[0].fallback_resource_class = ResourceClass.CPU
        templates = render_resource_claim_templates(
            intent, namespace="test-ns", dra_fallback=True
        )
        assert templates == []

    def test_fallback_emits_both_scheduler_and_kueue_templates(self):
        """A GPU step under dra_fallback yields TWO RCTs: the scheduler-route
        firstAvailable claim and the Kueue-route exactly claim."""
        templates = render_resource_claim_templates(
            _gpu_intent(), namespace="test-ns", dra_fallback=True
        )
        reqs = [t["spec"]["spec"]["devices"]["requests"][0] for t in templates]
        assert sum("firstAvailable" in r for r in reqs) == 1
        assert sum("exactly" in r for r in reqs) == 1

    def test_kueue_job_uses_exactly_not_first_available(self):
        """Kueue admission rejects firstAvailable (Inadmissible); the Kueue Job
        must reference the exactly GPU RCT and never the firstAvailable one."""
        intent = _gpu_intent()
        templates = render_resource_claim_templates(
            intent, namespace="test-ns", dra_fallback=True
        )
        fa = [t for t in templates
              if "firstAvailable" in t["spec"]["spec"]["devices"]["requests"][0]]
        ex = [t for t in templates
              if "exactly" in t["spec"]["spec"]["devices"]["requests"][0]]
        assert len(fa) == 1 and len(ex) == 1
        job = render_kueue_job(intent, dra_fallback=True)
        pod_claims = job["spec"]["template"]["spec"]["resourceClaims"]
        referenced = [c["resourceClaimTemplateName"] for c in pod_claims]
        assert ex[0]["metadata"]["name"] in referenced
        assert fa[0]["metadata"]["name"] not in referenced
        # the container references the pod-level claim by name
        container_claims = [
            c["name"]
            for c in job["spec"]["template"]["spec"]["containers"][0]["resources"]["claims"]
        ]
        assert set(container_claims) == {c["name"] for c in pod_claims}
