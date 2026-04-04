"""Tests for priority 0-100 → ORCHIDE 1-4 mapping.

ORCHIDE slide 9 uses priority 1-4 (1=highest). The schema uses 0-100
(higher=higher). The rendering layer converts via scale_priority_orchide().

Issue #53: formal priority mapping with tests.
"""

import pytest

from orbital_mission_compiler.compiler import (
    compile_plan_to_intents,
    load_mission_plan,
    render_argo_workflow,
    render_kueue_job,
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
