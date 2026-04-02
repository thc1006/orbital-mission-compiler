"""Tests for the Workflow Intent IR layer.

The IR (WorkflowIntent) is the boundary between plan parsing and rendering.
These tests verify IR structure independently of any renderer.
References: ORCHIDE slide 23 (Custom Translation Layer).
"""

from orbital_mission_compiler.compiler import (
    load_mission_plan,
    compile_plan_to_intents,
    render_argo_workflow,
    render_kueue_job,
)


def _load_intents(plan_file: str):
    plan = load_mission_plan(plan_file)
    return compile_plan_to_intents(plan)


# ── IR carries core identity fields ───────────────────────────────────


def test_ir_has_identity():
    """IR must carry mission_id, service_id, workflow_name, priority."""
    intents = _load_intents("configs/mission_plans/sample_maritime_surveillance.yaml")
    ir = intents[0]
    assert ir.mission_id == "mission-alpha"
    assert ir.service_id == "maritime-surveillance"
    assert ir.priority == 90
    assert "mission-alpha" in ir.workflow_name
    assert "maritime-surveillance" in ir.workflow_name


# ── IR carries resource summary ───────────────────────────────────────


def test_ir_resource_hints_gpu():
    """IR resource_hints must indicate GPU requirement."""
    intents = _load_intents("configs/mission_plans/sample_maritime_surveillance.yaml")
    hints = intents[0].resource_hints
    assert hints["requires_gpu"] is True
    assert hints["fallback_enabled"] is True


def test_ir_resource_hints_event_context():
    """IR resource_hints must carry event context (timestamp, visibility, region)."""
    intents = _load_intents("configs/mission_plans/sample_maritime_surveillance.yaml")
    hints = intents[0].resource_hints
    assert "event_timestamp" in hints
    assert "ground_visibility" in hints
    assert "region_type" in hints


# ── IR carries ORCHIDE slide 9 extended fields ────────────────────────


def test_ir_carries_landscape_type():
    """IR resource_hints should include landscape_type from the service (slide 9: TYPE)."""
    intents = _load_intents("configs/mission_plans/sample_orchide_format.yaml")
    hints = intents[0].resource_hints
    assert hints["landscape_type"] == "ocean"


def test_ir_carries_orbit():
    """IR resource_hints should include orbit from the event (slide 9: ORBIT)."""
    intents = _load_intents("configs/mission_plans/sample_orchide_format.yaml")
    hints = intents[0].resource_hints
    assert hints["orbit"] == 1


def test_ir_carries_duration():
    """IR resource_hints should include duration_seconds from the event (slide 9: DT_EV)."""
    intents = _load_intents("configs/mission_plans/sample_orchide_format.yaml")
    hints = intents[0].resource_hints
    assert hints["duration_seconds"] == 4.0


# ── IR carries execution_mode (slide 10) ─────────────────────────────


def test_ir_carries_execution_mode():
    """IR resource_hints should include execution_mode from the service (slide 10)."""
    intents = _load_intents("configs/mission_plans/sample_orchide_format.yaml")
    hints = intents[0].resource_hints
    assert hints["execution_mode"] == "sequential"


# ── IR is independent of renderers ────────────────────────────────────


def test_ir_inspectable_without_rendering():
    """IR can be serialized to dict without calling any renderer."""
    intents = _load_intents("configs/mission_plans/sample_orchide_format.yaml")
    ir = intents[0]
    data = ir.model_dump(mode="json")
    assert isinstance(data, dict)
    assert "mission_id" in data
    assert "steps" in data
    assert "resource_hints" in data


# ── IR consumed by both renderers ─────────────────────────────────────


def test_ir_consumed_by_argo_renderer():
    """Argo renderer should accept the IR without error."""
    intents = _load_intents("configs/mission_plans/sample_orchide_format.yaml")
    wf = render_argo_workflow(intents[0])
    assert wf["kind"] == "Workflow"


def test_ir_consumed_by_kueue_renderer():
    """Kueue renderer should accept the IR without error."""
    intents = _load_intents("configs/mission_plans/sample_orchide_format.yaml")
    job = render_kueue_job(intents[0])
    assert job["kind"] == "Job"


# ── Multi-service plan produces multiple IRs ──────────────────────────


def test_orchide_plan_produces_multiple_intents():
    """ORCHIDE format plan with 2 ACQ events × multiple services produces correct IR count."""
    intents = _load_intents("configs/mission_plans/sample_orchide_format.yaml")
    # Event 1: 2 services (maritime-surveillance, cloud-detection)
    # Event 2: 1 service (fire-detection)
    # Event 3: download (skipped)
    assert len(intents) == 3
    service_ids = [i.service_id for i in intents]
    assert "maritime-surveillance" in service_ids
    assert "cloud-detection" in service_ids
    assert "fire-detection" in service_ids
