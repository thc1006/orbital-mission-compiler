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
        # priority 75 -> ORCHIDE tier 2 -> orbital-mission-high
        assert job["metadata"]["labels"]["kueue.x-k8s.io/priority-class"] == "orbital-mission-high"

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
        assert by_name["orbital-mission-critical"] > by_name["orbital-mission-high"]
        assert by_name["orbital-mission-high"] > by_name["orbital-mission-normal"]
        assert by_name["orbital-mission-normal"] > by_name["orbital-mission-low"]

    def test_the_mapping_and_its_version_are_pinned_together(self):
        # Monotonicity is what the ordering proof needs, but it does not pin the
        # mapping: 400/250/200/150 is monotone too, and a change like that alters what
        # every class on a cluster means while leaving the rest of this file green.
        # The version exists to announce exactly that change, so the two are asserted
        # in one place -- changing either alone fails here, which is where someone has
        # to decide whether they have made a new mapping and say so in the label.
        from orbital_mission_compiler.compiler import PRIORITY_CLASS_MAPPING_VERSION

        assert PRIORITY_CLASS_MAPPING_VERSION == "v2"
        assert {w["metadata"]["name"]: w["value"] for w in render_workload_priority_classes()} == {
            "orbital-mission-critical": 400,
            "orbital-mission-high": 300,
            "orbital-mission-normal": 200,
            "orbital-mission-low": 100,
        }

    def test_higher_mission_priority_maps_to_higher_kueue_value(self):
        # The invariant the live queue-ordering proof (scripts/validate_kueue_priority.sh)
        # depends on: a higher mission priority renders a priority-class whose
        # WorkloadPriorityClass value is strictly higher, so Kueue sorts it ahead.
        value = {w["metadata"]["name"]: w["value"] for w in render_workload_priority_classes()}
        high = _priority_class_name(scale_priority_orchide(90))  # -> orbital-mission-critical
        low = _priority_class_name(scale_priority_orchide(50))   # -> orbital-mission-normal
        assert high == "orbital-mission-critical" and low == "orbital-mission-normal"
        assert value[high] > value[low]


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
        assert job["metadata"]["labels"]["kueue.x-k8s.io/priority-class"] == "orbital-mission-high"

    def test_custom_prefix_flows_to_classes_and_label(self, tmp_path, monkeypatch):
        import yaml

        self._run(tmp_path, monkeypatch, "--priority-class", "--emit-priority-classes",
                  "--priority-class-prefix", "mysat-")
        job = self._load_job(tmp_path)
        assert job["metadata"]["labels"]["kueue.x-k8s.io/priority-class"] == "mysat-mission-high"
        wpc = [d for d in yaml.safe_load_all((tmp_path / "workload-priority-classes.yaml").read_text()) if d]
        assert {d["metadata"]["name"] for d in wpc} == {
            f"mysat-{n}" for n in ("mission-critical", "mission-high", "mission-normal", "mission-low")
        }

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


def test_the_default_class_names_are_project_scoped():
    """A WorkloadPriorityClass is cluster-scoped, so a generic name is not ours to take.

    "mission-critical" is a name another installation, or an operator, can reasonably
    have created already, and emitting it would rewrite theirs. The prefix stays in the
    default so the emitted set belongs to something; an installation that shares a
    cluster with a second copy of this compiler can still set its own.
    """
    from orbital_mission_compiler.compiler import ORCHIDE_PRIORITY_CLASS_PREFIX

    assert ORCHIDE_PRIORITY_CLASS_PREFIX
    names = [w["metadata"]["name"] for w in render_workload_priority_classes()]
    assert all(n.startswith(ORCHIDE_PRIORITY_CLASS_PREFIX) for n in names)
    assert not any(n.startswith("mission-") for n in names)


def test_the_mapping_version_moved_with_the_names():
    """The constant's own comment says to bump it when the mapping changes."""
    from orbital_mission_compiler.compiler import PRIORITY_CLASS_MAPPING_VERSION

    assert PRIORITY_CLASS_MAPPING_VERSION == "v2"


def test_a_job_records_the_mapping_it_was_rendered_under():
    """The version has to travel with the Job, not only with the class objects.

    An earlier revision of this file said a Job carried the version it was labelled
    with. It did not: only the WorkloadPriorityClass objects were labelled, and a
    class name alone cannot say which mapping chose it, because the names survive a
    rename of what they mean and the objects are cluster-scoped and outlive the Job.
    Selecting on the label is the use, so it is a label.
    """
    from orbital_mission_compiler.compiler import PRIORITY_CLASS_MAPPING_VERSION

    intent = compile_plan_to_intents(
        load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
    )[0]

    labelled = render_kueue_job(intent, priority_class=True)["metadata"]["labels"]
    assert labelled["orbital/priority-mapping-version"] == PRIORITY_CLASS_MAPPING_VERSION
    assert labelled["kueue.x-k8s.io/priority-class"] == "orbital-mission-high"

    # Without a class reference there is no mapping to record.
    plain = render_kueue_job(intent, priority_class=False)["metadata"]["labels"]
    assert "orbital/priority-mapping-version" not in plain


def test_the_job_and_the_classes_agree_on_the_mapping_version():
    """A Job labelled v2 has to be pointing at classes emitted by the same mapping."""
    intent = compile_plan_to_intents(
        load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
    )[0]
    job = render_kueue_job(intent, priority_class=True)["metadata"]["labels"]
    classes = {
        w["metadata"]["name"]: w["metadata"]["labels"]["orbital/priority-mapping-version"]
        for w in render_workload_priority_classes()
    }

    referenced = job["kueue.x-k8s.io/priority-class"]
    assert referenced in classes
    assert classes[referenced] == job["orbital/priority-mapping-version"]
