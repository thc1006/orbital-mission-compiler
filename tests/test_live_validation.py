"""Tests for live cluster validation mission plan.

Validates that the validation_live_cluster.yaml plan loads, compiles,
and renders valid Argo/Kueue YAML. Optionally runs argo lint if the
CLI is available. Does NOT submit to a live cluster.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

from orbital_mission_compiler.compiler import (
    compile_plan_to_intents,
    load_mission_plan,
    render_argo_workflow,
    render_kueue_job,
    write_individual_workflows,
)

VALIDATION_PLAN = "configs/mission_plans/validation_live_cluster.yaml"

ARGO_CLI_AVAILABLE = shutil.which("argo") is not None


class TestValidationPlanLoad:
    """Test that the validation mission plan loads and parses correctly."""

    def test_plan_file_exists(self):
        assert Path(VALIDATION_PLAN).is_file(), (
            f"Validation plan not found: {VALIDATION_PLAN}"
        )

    def test_plan_loads_successfully(self):
        plan = load_mission_plan(VALIDATION_PLAN)
        assert plan.mission_id == "validation-live"
        assert plan.client_id == "paper-validation"

    def test_plan_has_acquisition_event(self):
        plan = load_mission_plan(VALIDATION_PLAN)
        acq_events = [e for e in plan.events if e.event_type.value == "acquisition"]
        assert len(acq_events) >= 1, "Validation plan must have at least one acquisition event"

    def test_plan_uses_cpu_only(self):
        """Validation plan should use CPU-only to avoid GPU dependency."""
        plan = load_mission_plan(VALIDATION_PLAN)
        for event in plan.events:
            for svc in event.services:
                for step in svc.steps:
                    assert step.resource_class.value == "cpu", (
                        f"Step {step.name!r} uses {step.resource_class.value}, "
                        "expected cpu for validation plan"
                    )


class TestValidationPlanCompile:
    """Test that the validation plan compiles to valid workflow intents."""

    def test_compiles_to_intents(self):
        plan = load_mission_plan(VALIDATION_PLAN)
        intents = compile_plan_to_intents(plan)
        assert len(intents) >= 1, "Must produce at least one workflow intent"

    def test_intent_metadata(self):
        plan = load_mission_plan(VALIDATION_PLAN)
        intents = compile_plan_to_intents(plan)
        intent = intents[0]
        assert intent.mission_id == "validation-live"
        assert intent.service_id == "ship-detection"
        assert intent.resource_hints["requires_gpu"] is False


class TestValidationArgoRendering:
    """Test that rendered Argo Workflow YAML is structurally valid."""

    def test_renders_argo_workflow(self):
        plan = load_mission_plan(VALIDATION_PLAN)
        intents = compile_plan_to_intents(plan)
        wf = render_argo_workflow(intents[0])
        assert wf["apiVersion"] == "argoproj.io/v1alpha1"
        assert wf["kind"] == "Workflow"
        assert "spec" in wf
        assert "entrypoint" in wf["spec"]

    def test_argo_workflow_has_three_steps(self):
        plan = load_mission_plan(VALIDATION_PLAN)
        intents = compile_plan_to_intents(plan)
        wf = render_argo_workflow(intents[0])
        # main DAG template + 3 step templates = 4 templates total
        templates = wf["spec"]["templates"]
        step_templates = [t for t in templates if t["name"] != "main"]
        assert len(step_templates) == 3, (
            f"Expected 3 step templates, got {len(step_templates)}"
        )

    def test_argo_workflow_uses_busybox(self):
        plan = load_mission_plan(VALIDATION_PLAN)
        intents = compile_plan_to_intents(plan)
        wf = render_argo_workflow(intents[0])
        for tmpl in wf["spec"]["templates"]:
            if "container" in tmpl:
                assert tmpl["container"]["image"].startswith("busybox:"), (
                    f"Validation plan should use busybox, got {tmpl['container']['image']}"
                )

    def test_write_individual_workflows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            written = write_individual_workflows(VALIDATION_PLAN, tmpdir)
            assert len(written) >= 1
            for path in written:
                assert path.exists()
                obj = yaml.safe_load(path.read_text(encoding="utf-8"))
                assert obj["kind"] == "Workflow"

    @pytest.mark.skipif(
        not ARGO_CLI_AVAILABLE,
        reason="argo CLI not available",
    )
    def test_argo_lint_passes(self):
        """Rendered Argo YAML passes official argo lint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            written = write_individual_workflows(VALIDATION_PLAN, tmpdir)
            for path in written:
                result = subprocess.run(
                    ["argo", "lint", str(path)],
                    capture_output=True,
                    text=True,
                )
                assert result.returncode == 0, (
                    f"argo lint failed for {path.name}:\n{result.stderr}"
                )


class TestValidationKueueRendering:
    """Test that rendered Kueue Job YAML is structurally valid."""

    def test_renders_kueue_job(self):
        plan = load_mission_plan(VALIDATION_PLAN)
        intents = compile_plan_to_intents(plan)
        job = render_kueue_job(intents[0])
        assert job["apiVersion"] == "batch/v1"
        assert job["kind"] == "Job"

    def test_kueue_job_no_gpu_resources(self):
        """CPU-only plan should not request GPU resources."""
        plan = load_mission_plan(VALIDATION_PLAN)
        intents = compile_plan_to_intents(plan)
        job = render_kueue_job(intents[0])
        pod_spec = job["spec"]["template"]["spec"]
        assert "nodeSelector" not in pod_spec
        assert "tolerations" not in pod_spec
        resources = pod_spec["containers"][0].get("resources", {})
        assert "nvidia.com/gpu" not in resources.get("requests", {})
