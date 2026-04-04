"""Tests for Argo and Kueue rendering hardening.

Verifies rendered YAML carries phase annotations, priority metadata,
and runtime hints from the IR. Does NOT test live cluster behavior.
"""

from orbital_mission_compiler.compiler import (
    load_mission_plan,
    compile_plan_to_intents,
    render_argo_workflow,
    render_kueue_job,
)


def _intents(plan_file):
    return compile_plan_to_intents(load_mission_plan(plan_file))


# ── Argo: phase annotation on templates ──────────────────────────────


def test_argo_template_has_phase_annotation():
    """Argo templates should annotate the step phase (slide 10)."""
    intent = _intents("configs/mission_plans/sample_orchide_format.yaml")[0]
    wf = render_argo_workflow(intent)
    # step-0-preprocess template
    preprocess = [t for t in wf["spec"]["templates"] if t["name"] == "step-0-preprocess"][0]
    assert preprocess["metadata"]["annotations"]["phase"] == "preprocessing"

    # step-1-detect-ships (AI phase)
    detect = [t for t in wf["spec"]["templates"] if t["name"] == "step-1-detect-ships"][0]
    assert detect["metadata"]["annotations"]["phase"] == "ai"


def test_argo_template_phase_absent_when_none():
    """Templates without phase should not have a phase annotation."""
    intent = _intents("configs/mission_plans/sample_maritime_surveillance.yaml")[0]
    wf = render_argo_workflow(intent)
    preprocess = [t for t in wf["spec"]["templates"] if t["name"] == "step-0-preprocess"][0]
    assert "phase" not in preprocess["metadata"]["annotations"]


# ── Argo: priority in workflow annotations ───────────────────────────


def test_argo_workflow_has_priority_annotation():
    """Workflow metadata should carry priority as annotation for scheduling."""
    intent = _intents("configs/mission_plans/sample_orchide_format.yaml")[0]
    wf = render_argo_workflow(intent)
    annotations = wf["metadata"].get("annotations", {})
    assert annotations["orbital/priority"] == "90"


# ── Argo: resource hints in workflow annotations ─────────────────────


def test_argo_workflow_has_resource_annotations():
    """Workflow should annotate GPU/FPGA requirements for cluster-level visibility."""
    intent = _intents("configs/mission_plans/sample_orchide_format.yaml")[0]
    wf = render_argo_workflow(intent)
    annotations = wf["metadata"].get("annotations", {})
    assert annotations["orbital/requires-gpu"] == "true"


# ── Kueue: priority label ────────────────────────────────────────────


def test_kueue_job_has_priority_annotation():
    """Kueue Job should carry priority as annotation (not just label)."""
    intent = _intents("configs/mission_plans/sample_orchide_format.yaml")[0]
    job = render_kueue_job(intent)
    annotations = job["metadata"].get("annotations", {})
    assert annotations["orbital/priority"] == "90"


def test_kueue_job_has_resource_annotations():
    """Kueue Job should annotate resource requirements."""
    intent = _intents("configs/mission_plans/sample_orchide_format.yaml")[0]
    job = render_kueue_job(intent)
    annotations = job["metadata"].get("annotations", {})
    assert annotations["orbital/requires-gpu"] == "true"
