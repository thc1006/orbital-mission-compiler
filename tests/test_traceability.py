"""Tests for ORCHIDE schema traceability matrix completeness.

Verifies that docs/14_traceability_matrix.md covers every schema field,
OPA policy rule, and WorkflowIntent resource hint. Uses Python
introspection so that any new field/rule added without a traceability
entry causes an immediate test failure.

Issue #51: ORCHIDE schema traceability appendix.
Reviewer feedback: R1 Major #6, R2 Major #5, R3 Major #5.
"""

import re
from pathlib import Path

import pytest

from orbital_mission_compiler.schemas import (
    AIService,
    ExecutionMode,
    MissionEvent,
    MissionEventType,
    MissionPlan,
    ResourceClass,
    StepPhase,
    WorkflowStep,
)

TRACEABILITY_DOC = Path("docs/14_traceability_matrix.md")

# ── Helpers ──────────────────────────────────────────────────────────────

def _read_doc() -> str:
    """Read the traceability document, skip if missing."""
    if not TRACEABILITY_DOC.is_file():
        pytest.skip(f"{TRACEABILITY_DOC} not yet created")
    return TRACEABILITY_DOC.read_text(encoding="utf-8")


def _model_field_names(model_cls: type) -> set[str]:
    """Return field names from a Pydantic BaseModel."""
    return set(model_cls.model_fields.keys())


def _enum_member_names(enum_cls: type) -> set[str]:
    """Return member values from a str Enum."""
    return {m.value for m in enum_cls}


def _extract_rego_rules(rego_path: str = "configs/policies/mission_plan.rego") -> list[str]:
    """Extract deny rule messages from the Rego file."""
    text = Path(rego_path).read_text(encoding="utf-8")
    # Match msg := "..." and msg := sprintf("...", [...])
    return re.findall(r'msg\s*:=\s*(?:sprintf\()?"([^"]+)"', text)


def _resource_hints_keys() -> set[str]:
    """Return the set of resource_hints keys built in compile_plan_to_intents."""
    return {
        "event_timestamp",
        "ground_visibility",
        "region_type",
        "orbit",
        "duration_seconds",
        "landscape_type",
        "execution_mode",
        "requires_gpu",
        "requires_fpga",
        "fallback_enabled",
    }


# ── Document existence ───────────────────────────────────────────────────

class TestTraceabilityDocExists:
    """The traceability document must exist and have required sections."""

    def test_doc_file_exists(self):
        assert TRACEABILITY_DOC.is_file(), (
            f"Traceability document missing: {TRACEABILITY_DOC}"
        )

    def test_has_schema_field_table(self):
        doc = _read_doc()
        assert "Schema Field Traceability" in doc, (
            "Document must contain a 'Schema Field Traceability' section"
        )

    def test_has_opa_policy_table(self):
        doc = _read_doc()
        assert "OPA Policy Rule Traceability" in doc, (
            "Document must contain an 'OPA Policy Rule Traceability' section"
        )

    def test_has_resource_hints_table(self):
        doc = _read_doc()
        assert "Resource Hints Traceability" in doc, (
            "Document must contain a 'Resource Hints Traceability' section"
        )

    def test_has_ground_side_rationale(self):
        doc = _read_doc()
        assert "Ground-Side" in doc or "Author-Imposed" in doc, (
            "Document must explain ground-side / author-imposed additions"
        )


# ── Schema field completeness ────────────────────────────────────────────

class TestSchemaFieldCompleteness:
    """Every Pydantic model field must appear in the traceability doc."""

    @pytest.mark.parametrize("field", sorted(_model_field_names(MissionPlan)))
    def test_mission_plan_field_traced(self, field: str):
        doc = _read_doc()
        assert f"`{field}`" in doc or f"| {field} " in doc or f"|{field}|" in doc, (
            f"MissionPlan.{field} not found in traceability doc"
        )

    @pytest.mark.parametrize("field", sorted(_model_field_names(MissionEvent)))
    def test_mission_event_field_traced(self, field: str):
        doc = _read_doc()
        assert f"`{field}`" in doc or f"| {field} " in doc or f"|{field}|" in doc, (
            f"MissionEvent.{field} not found in traceability doc"
        )

    @pytest.mark.parametrize("field", sorted(_model_field_names(AIService)))
    def test_ai_service_field_traced(self, field: str):
        doc = _read_doc()
        assert f"`{field}`" in doc or f"| {field} " in doc or f"|{field}|" in doc, (
            f"AIService.{field} not found in traceability doc"
        )

    @pytest.mark.parametrize("field", sorted(_model_field_names(WorkflowStep)))
    def test_workflow_step_field_traced(self, field: str):
        doc = _read_doc()
        assert f"`{field}`" in doc or f"| {field} " in doc or f"|{field}|" in doc, (
            f"WorkflowStep.{field} not found in traceability doc"
        )


# ── Enum completeness ────────────────────────────────────────────────────

class TestEnumCompleteness:
    """Every enum value must appear in the traceability doc."""

    @pytest.mark.parametrize("value", sorted(_enum_member_names(ResourceClass)))
    def test_resource_class_traced(self, value: str):
        doc = _read_doc()
        assert value in doc.lower(), (
            f"ResourceClass.{value} not found in traceability doc"
        )

    @pytest.mark.parametrize("value", sorted(_enum_member_names(StepPhase)))
    def test_step_phase_traced(self, value: str):
        doc = _read_doc()
        assert value in doc.lower(), (
            f"StepPhase.{value} not found in traceability doc"
        )

    @pytest.mark.parametrize("value", sorted(_enum_member_names(ExecutionMode)))
    def test_execution_mode_traced(self, value: str):
        doc = _read_doc()
        assert value in doc.lower(), (
            f"ExecutionMode.{value} not found in traceability doc"
        )

    @pytest.mark.parametrize("value", sorted(_enum_member_names(MissionEventType)))
    def test_event_type_traced(self, value: str):
        doc = _read_doc()
        assert value in doc.lower(), (
            f"MissionEventType.{value} not found in traceability doc"
        )


# ── OPA policy rule completeness ─────────────────────────────────────────

class TestOpaPolicyCompleteness:
    """Every OPA deny rule must appear in the traceability doc."""

    @pytest.mark.parametrize(
        "rule_msg",
        _extract_rego_rules(),
        ids=[f"rule-{i+1}" for i in range(len(_extract_rego_rules()))],
    )
    def test_opa_rule_traced(self, rule_msg: str):
        doc = _read_doc()
        # Check for the rule message or a close keyword from it
        keywords = [w for w in rule_msg.split() if len(w) > 4][:3]
        found = any(kw.lower() in doc.lower() for kw in keywords)
        assert found, (
            f"OPA rule not found in traceability doc: {rule_msg!r}\n"
            f"Searched keywords: {keywords}"
        )


# ── Resource hints completeness ──────────────────────────────────────────

class TestResourceHintsCompleteness:
    """Every resource_hints key must appear in the traceability doc."""

    @pytest.mark.parametrize("hint_key", sorted(_resource_hints_keys()))
    def test_resource_hint_traced(self, hint_key: str):
        doc = _read_doc()
        assert f"`{hint_key}`" in doc or f"| {hint_key} " in doc or f"|{hint_key}|" in doc, (
            f"resource_hints[{hint_key!r}] not found in traceability doc"
        )


# ── Cross-reference integrity ────────────────────────────────────────────

class TestCrossReferences:
    """Traceability doc must reference ORCHIDE slides and D3.1 sections."""

    def test_references_slide_9(self):
        doc = _read_doc()
        assert "slide 9" in doc.lower() or "Slide 9" in doc, (
            "Must reference Slide 9 (mission plan table format)"
        )

    def test_references_slide_10(self):
        doc = _read_doc()
        assert "slide 10" in doc.lower() or "Slide 10" in doc, (
            "Must reference Slide 10 (workflow pipeline)"
        )

    def test_references_slide_14(self):
        doc = _read_doc()
        assert "slide 14" in doc.lower() or "Slide 14" in doc, (
            "Must reference Slide 14 (heterogeneous hardware)"
        )

    def test_references_slide_23(self):
        doc = _read_doc()
        assert "slide 23" in doc.lower() or "Slide 23" in doc, (
            "Must reference Slide 23 (custom translation layer)"
        )

    def test_references_d3_1(self):
        doc = _read_doc()
        assert "D3.1" in doc, (
            "Must reference ORCHIDE D3.1 deliverable"
        )
