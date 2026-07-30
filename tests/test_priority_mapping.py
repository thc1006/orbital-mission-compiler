"""Tests for priority 0-100 → ORCHIDE 1-4 mapping.

ORCHIDE slide 9 uses priority 1-4 (1=highest). The schema uses 0-100
(higher=higher). The rendering layer converts via scale_priority_orchide().

Issue #53: formal priority mapping with tests.
"""

import pytest

from orbital_mission_compiler.compiler import (
    _priority_class_name,
    compile_plan_to_intents,
    load_mission_plan,
    render_argo_workflow,
    render_kueue_job,
    render_workload_priority_classes,
    scale_priority_orchide,
)


# ── Mapping function ─────────────────────────────────────────────────────


class TestScalePriorityOrchide:
    """scale_priority_orchide converts 0-100 to ORCHIDE 1-4 scale."""

    @pytest.mark.parametrize(
        "input_val, expected",
        [
            (1, 4),    # lowest bucket
            (25, 4),   # top of lowest bucket
            (26, 3),   # bottom of second bucket
            (50, 3),   # top of second bucket
            (51, 2),   # bottom of third bucket
            (75, 2),   # top of third bucket
            (76, 1),   # bottom of highest bucket
            (100, 1),  # max → highest
        ],
    )
    def test_mapping_boundaries(self, input_val: int, expected: int):
        assert scale_priority_orchide(input_val) == expected

    def test_zero_raises(self):
        """Priority 0 is a misconfiguration (OPA rule 5 rejects it)."""
        with pytest.raises(ValueError, match="priority 0"):
            scale_priority_orchide(0)

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="out of range"):
            scale_priority_orchide(-1)

    def test_over_100_raises(self):
        with pytest.raises(ValueError, match="out of range"):
            scale_priority_orchide(101)


# ── Argo annotation ──────────────────────────────────────────────────────


class TestArgoPriorityAnnotation:
    """Argo Workflow annotations include both raw and ORCHIDE-scaled priority."""

    def test_argo_has_orchide_priority(self):
        plan = load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
        intent = compile_plan_to_intents(plan)[0]
        wf = render_argo_workflow(intent)
        annotations = wf["metadata"]["annotations"]
        assert "orbital/orchide-priority" in annotations

    def test_argo_orchide_priority_value(self):
        plan = load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
        intent = compile_plan_to_intents(plan)[0]
        # sample_gpu_cpu_fallback has priority=75 → ORCHIDE 2
        wf = render_argo_workflow(intent)
        assert wf["metadata"]["annotations"]["orbital/orchide-priority"] == "2"

    def test_argo_keeps_raw_priority(self):
        plan = load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
        intent = compile_plan_to_intents(plan)[0]
        wf = render_argo_workflow(intent)
        assert wf["metadata"]["annotations"]["orbital/priority"] == "75"


# ── Kueue annotation ─────────────────────────────────────────────────────


class TestKueuePriorityAnnotation:
    """Kueue Job annotations include both raw and ORCHIDE-scaled priority."""

    def test_kueue_has_orchide_priority(self):
        plan = load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
        intent = compile_plan_to_intents(plan)[0]
        job = render_kueue_job(intent)
        annotations = job["metadata"]["annotations"]
        assert "orbital/orchide-priority" in annotations

    def test_kueue_orchide_priority_value(self):
        plan = load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
        intent = compile_plan_to_intents(plan)[0]
        job = render_kueue_job(intent)
        assert job["metadata"]["annotations"]["orbital/orchide-priority"] == "2"

    def test_kueue_keeps_raw_priority(self):
        plan = load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
        intent = compile_plan_to_intents(plan)[0]
        job = render_kueue_job(intent)
        assert job["metadata"]["annotations"]["orbital/priority"] == "75"


# ── Kueue WorkloadPriorityClass (priority actually drives Kueue) ─────────────


class TestKueueWorkloadPriorityClass:
    """The Kueue Job carries a kueue.x-k8s.io/priority-class label that Kueue
    reads, so mission priority drives admission ordering and preemption."""

    def test_priority_class_label_opt_in(self):
        plan = load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
        intent = compile_plan_to_intents(plan)[0]
        job = render_kueue_job(intent, priority_class=True)
        # priority 75 -> ORCHIDE tier 2 -> orbital-orchide-2
        assert job["metadata"]["labels"]["kueue.x-k8s.io/priority-class"] == "orbital-orchide-2"

    def test_priority_class_off_by_default(self):
        # Default off: the referenced WorkloadPriorityClass must exist first
        # (Kueue errors on a missing class), so the label is not emitted unless
        # opted in -- no regression for callers that do not apply the classes.
        plan = load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
        intent = compile_plan_to_intents(plan)[0]
        job = render_kueue_job(intent)
        assert "kueue.x-k8s.io/priority-class" not in job["metadata"]["labels"]

    def test_render_priority_classes_four_tiers_monotone(self):
        wpcs = render_workload_priority_classes()
        assert len(wpcs) == 4
        assert all(w["kind"] == "WorkloadPriorityClass" for w in wpcs)
        assert all(w["apiVersion"] == "kueue.x-k8s.io/v1beta2" for w in wpcs)
        by_name = {w["metadata"]["name"]: w["value"] for w in wpcs}
        # ORCHIDE 1 is highest priority -> highest Kueue value; strictly monotone.
        assert by_name["orbital-orchide-1"] > by_name["orbital-orchide-2"]
        assert by_name["orbital-orchide-2"] > by_name["orbital-orchide-3"]
        assert by_name["orbital-orchide-3"] > by_name["orbital-orchide-4"]


# ── WorkloadPriorityClass is reachable from the CLI (#6) ─────────────────


class TestKueueCliPriorityClass:
    """The render-kueue command can emit the cluster-scoped classes and label Jobs."""

    PLAN = "configs/mission_plans/sample_gpu_cpu_fallback.yaml"  # priority 75 -> tier 2

    def _run(self, tmp_path, monkeypatch, *extra):
        import sys

        from orbital_mission_compiler.cli import main

        argv = ["prog", "render-kueue", "--input", self.PLAN, "--output-dir", str(tmp_path),
                "--policy-engine", "baseline", *extra]
        monkeypatch.setattr(sys, "argv", argv)
        main()

    def _load_job(self, tmp_path):
        import yaml

        job_file = next(p for p in tmp_path.glob("*-kueue.yaml"))
        docs = [d for d in yaml.safe_load_all(job_file.read_text()) if d]
        return next(d for d in docs if d.get("kind") == "Job")

    def test_emit_priority_classes_writes_four(self, tmp_path, monkeypatch):
        import yaml

        self._run(tmp_path, monkeypatch, "--emit-priority-classes")
        wpc = tmp_path / "workload-priority-classes.yaml"
        assert wpc.exists()
        docs = [d for d in yaml.safe_load_all(wpc.read_text()) if d]
        assert sum(d.get("kind") == "WorkloadPriorityClass" for d in docs) == 4

    def test_priority_class_labels_the_job(self, tmp_path, monkeypatch):
        self._run(tmp_path, monkeypatch, "--priority-class")
        job = self._load_job(tmp_path)
        assert job["metadata"]["labels"]["kueue.x-k8s.io/priority-class"] == "orbital-orchide-2"

    def test_custom_prefix_flows_to_classes_and_label(self, tmp_path, monkeypatch):
        import yaml

        self._run(tmp_path, monkeypatch, "--priority-class", "--emit-priority-classes",
                  "--priority-class-prefix", "mysat-")
        job = self._load_job(tmp_path)
        assert job["metadata"]["labels"]["kueue.x-k8s.io/priority-class"] == "mysat-2"
        wpc = [d for d in yaml.safe_load_all((tmp_path / "workload-priority-classes.yaml").read_text()) if d]
        assert {d["metadata"]["name"] for d in wpc} == {f"mysat-{t}" for t in (1, 2, 3, 4)}

    def test_no_priority_class_label_by_default(self, tmp_path, monkeypatch):
        self._run(tmp_path, monkeypatch)
        job = self._load_job(tmp_path)
        assert "kueue.x-k8s.io/priority-class" not in job["metadata"].get("labels", {})


# ── WorkloadPriorityClass prefix validation (PR #77 external review, P2-2) ──


class TestPriorityClassPrefixValidation:
    """A custom prefix must be rejected at render time, not on apply.

    The generated string is both a cluster-scoped object name and a label value
    on the Job, so an invalid or overlong prefix otherwise produces YAML that
    only fails once it reaches the API server.
    """

    @pytest.mark.parametrize(
        "prefix",
        [
            "THIS_IS_INVALID/",  # uppercase, underscore and a slash
            "has space-",
            "-leading-dash",
            "x" * 70,  # exceeds the 63-character label bound
        ],
    )
    def test_invalid_prefix_is_rejected(self, prefix):
        with pytest.raises(ValueError, match="RFC 1123 label"):
            _priority_class_name(1, prefix=prefix)

    def test_valid_prefix_is_accepted(self):
        assert _priority_class_name(1, prefix="mysat-").startswith("mysat-")
