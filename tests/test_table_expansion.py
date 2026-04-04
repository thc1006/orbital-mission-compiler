"""Tests for expanded comparison table completeness.

Verifies that docs/16_comparison_table.md covers all reviewer-requested
dimensions and related systems.

Issue #53: Expand Table I comparison dimensions.
"""

from pathlib import Path

import pytest

TABLE_DOC = Path("docs/16_comparison_table.md")


def _read_doc() -> str:
    if not TABLE_DOC.is_file():
        pytest.skip(f"{TABLE_DOC} not yet created")
    return TABLE_DOC.read_text(encoding="utf-8")


class TestDocumentStructure:

    def test_doc_exists(self):
        assert TABLE_DOC.is_file(), f"Comparison table missing: {TABLE_DOC}"

    def test_has_multi_system_table(self):
        doc = _read_doc()
        assert "ORCHIDE" in doc and "EOEPCA" in doc, (
            "Must compare against ORCHIDE and EOEPCA+"
        )


class TestReviewerRequestedDimensions:
    """Reviewer asked for: problem layer, artifact granularity, scheduling scope."""

    @pytest.mark.parametrize("dimension", [
        "Problem Layer",
        "Artifact Granularity",
        "Scheduling Scope",
    ])
    def test_reviewer_dimension_present(self, dimension: str):
        doc = _read_doc()
        assert dimension.lower() in doc.lower(), (
            f"Reviewer-requested dimension missing: {dimension}"
        )


class TestAdditionalDimensions:
    """Additional comparison dimensions with exact labels."""

    @pytest.mark.parametrize("dimension", [
        "Validation Approach",
        "Policy Framework",
        "Defense-in-Depth",
        "Hardware Abstraction",
        "Extensibility Model",
        "AI Agent Interface",
        "Execution Environment",
        "CCSDS Alignment",
        "Open Source",
    ])
    def test_dimension_present(self, dimension: str):
        doc = _read_doc()
        assert dimension in doc, (
            f"Comparison dimension missing: {dimension}"
        )


class TestComparedSystems:
    """All 5 compared systems must be present."""

    @pytest.mark.parametrize("system", [
        "ORCHIDE",
        "EOEPCA",
        "KubeSpace",
        "DLR Sentinel+Argo",
        "This compiler",
    ])
    def test_system_compared(self, system: str):
        doc = _read_doc()
        assert system in doc, f"System not compared: {system}"
