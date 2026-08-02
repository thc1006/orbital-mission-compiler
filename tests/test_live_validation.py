"""Tests for live cluster validation mission plan.

Validates that the validation_live_cluster.yaml plan loads, compiles,
and renders valid Argo/Kueue YAML. Optionally runs argo lint if the
CLI is available. Does NOT submit to a live cluster.
"""

import inspect
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
        """Rendered Argo YAML passes official argo lint.

        `--offline` because this asserts something about the manifest, not about
        a cluster: without it the CLI looks for a kubeconfig and the test fails
        wherever there is no cluster, which is everywhere this suite runs in CI.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            written = write_individual_workflows(VALIDATION_PLAN, tmpdir)
            for path in written:
                result = subprocess.run(
                    ["argo", "lint", "--offline", "--no-color", str(path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                assert result.returncode == 0, (
                    f"argo lint failed for {path.name}:\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
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

class TestLiveScriptControlFlow:
    """The order the live script does things in, which running it is the only other way to check.

    CI does not run scripts/validate_live_cluster.sh, and the tests above deliberately
    stop short of a cluster, so nothing else here would notice the script rendering
    into the destination, reporting a lint failure and submitting the Workflow anyway.
    These read the script.
    """

    SCRIPT = Path("scripts/validate_live_cluster.sh")

    def _text(self) -> str:
        return self.SCRIPT.read_text(encoding="utf-8")

    def _lines(self) -> list[str]:
        return self._text().split("\n")

    def test_the_workflow_is_published_through_the_gate(self):
        """Rendering first and checking afterwards leaves the manifests where a
        caller that ignores the verdict will apply them."""
        text = self._text()
        assert "--argo-lint" in text
        # The standalone linter run this replaced took the rendered files as
        # arguments; the gate is the only linter invocation now.
        assert 'argo lint "${files[@]}"' not in text

    def test_submission_is_conditional_on_the_gate(self):
        lines = self._lines()
        submit = next(i for i, line in enumerate(lines) if "argo submit" in line and not line.strip().startswith("#"))
        guard = "\n".join(lines[max(0, submit - 3) : submit + 1])
        assert "ARGO_GATE_OK" in guard, f"argo submit is not guarded by the gate result:\n{guard}"

    def test_the_teardown_is_installed_before_anything_is_created(self):
        """Registering it after the submission left a window where an interrupt
        kept the Workflow."""
        lines = self._lines()
        body = self._function_span(lines, "cleanup_all")
        traps = [i for i, line in enumerate(lines) if line.lstrip().startswith("trap ")]
        mutations = [
            i
            for i, line in enumerate(lines)
            if not (body[0] <= i <= body[1])
            and not line.strip().startswith("#")
            and ("argo submit" in line or any(f"kubectl {verb}" in line for verb in ("apply", "create", "delete", "patch")))
        ]
        assert traps and mutations
        assert max(traps) < min(mutations), (
            f"a cluster mutation at line {min(mutations) + 1} precedes the trap at {max(traps) + 1}"
        )

    def test_the_script_does_not_claim_a_lint_mode_it_does_not_use(self):
        """The gate passes --offline, so the script cannot be doing a cluster-aware lint.

        The comment saying otherwise described the standalone `argo lint` call that
        publishing through the gate replaced.
        """
        from orbital_mission_compiler import compiler

        gate_source = inspect.getsource(compiler.argo_lint_path)
        assert "--offline" in gate_source

        text = self._text()
        assert "cluster-aware lint is the stronger one" not in text
        assert "The gate lints offline" in text

    def test_the_signal_handlers_stop_the_script(self):
        """Without set -e a handler that returns lets the run continue and recreate
        what it has just deleted."""
        text = self._text()
        assert "exit 130" in text and "exit 143" in text

    @staticmethod
    def _function_span(lines: list[str], name: str) -> tuple[int, int]:
        start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}()"))
        end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "}")
        return start, end
