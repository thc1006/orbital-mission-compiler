"""Tests for AI Service workflow phase model (ORCHIDE slide 10).

Slide 10: Each AI Service = Pre-processing → AI → Post-processing,
configured to be launched sequentially or in parallel.
"""

import pytest
from pydantic import ValidationError

from orbital_mission_compiler.schemas import (
    AIService,
    WorkflowStep,
    ResourceClass,
    StepPhase,
)
from orbital_mission_compiler.compiler import load_mission_plan, compile_plan_to_intents


def _step(name="s", phase=None, **kwargs):
    defaults = {"name": name, "image": "img:latest", "resource_class": ResourceClass.CPU}
    defaults.update(kwargs)
    if phase is not None:
        defaults["phase"] = phase
    return WorkflowStep(**defaults)


# ── StepPhase enum ────────────────────────────────────────────────────


def test_step_phase_values():
    """StepPhase must have preprocessing, ai, postprocessing (slide 10)."""
    assert StepPhase.PREPROCESSING == "preprocessing"
    assert StepPhase.AI == "ai"
    assert StepPhase.POSTPROCESSING == "postprocessing"


def test_step_accepts_phase():
    """WorkflowStep should accept a phase field."""
    step = _step("preprocess", phase=StepPhase.PREPROCESSING)
    assert step.phase == StepPhase.PREPROCESSING


def test_step_phase_optional():
    """Phase is optional for backward compatibility."""
    step = _step("generic")
    assert step.phase is None


def test_reject_invalid_phase():
    """Invalid phase value must be rejected."""
    with pytest.raises(ValidationError):
        _step("bad", phase="launch")


# ── AIService execution mode ─────────────────────────────────────────


def test_service_default_sequential():
    """Default execution_mode should be sequential (slide 10: steps can be sequential or parallel)."""
    svc = AIService(
        service_id="test",
        priority=1,
        steps=[_step("s1")],
    )
    assert svc.execution_mode == "sequential"


def test_service_accepts_parallel():
    """Service should accept execution_mode=parallel."""
    svc = AIService(
        service_id="test",
        priority=1,
        execution_mode="parallel",
        steps=[_step("s1"), _step("s2")],
    )
    assert svc.execution_mode == "parallel"


def test_reject_invalid_execution_mode():
    """Invalid execution_mode must be rejected."""
    with pytest.raises(ValidationError):
        AIService(
            service_id="test",
            priority=1,
            execution_mode="random",
            steps=[_step("s1")],
        )


# ── Full pipeline: pre → ai → post ──────────────────────────────────


def test_three_phase_service():
    """A service with all three phases should validate."""
    svc = AIService(
        service_id="maritime-surveillance",
        priority=1,
        steps=[
            _step("preprocess", phase=StepPhase.PREPROCESSING),
            _step("detect", phase=StepPhase.AI, resource_class=ResourceClass.GPU),
            _step("postprocess", phase=StepPhase.POSTPROCESSING),
        ],
    )
    phases = [s.phase for s in svc.steps]
    assert phases == [StepPhase.PREPROCESSING, StepPhase.AI, StepPhase.POSTPROCESSING]


# ── IR carries phase info ────────────────────────────────────────────


def test_ir_preserves_step_phases():
    """WorkflowIntent IR should carry phase annotations from plan steps."""
    plan = load_mission_plan("configs/mission_plans/sample_orchide_format.yaml")
    intents = compile_plan_to_intents(plan)
    # First intent = maritime-surveillance with 3 steps
    ir = intents[0]
    phases = [s.phase for s in ir.steps]
    assert phases == [StepPhase.PREPROCESSING, StepPhase.AI, StepPhase.POSTPROCESSING]


# ── Backward compatibility ───────────────────────────────────────────


def test_existing_plans_still_valid():
    """Plans without phase annotations must still load."""
    plan = load_mission_plan("configs/mission_plans/sample_maritime_surveillance.yaml")
    assert plan.mission_id == "mission-alpha"
    # Steps have no phase → all None
    for step in plan.events[0].services[0].steps:
        assert step.phase is None
