"""Tests for threat model and CCSDS terminology document completeness.

Verifies that docs/15_threat_model.md covers all trust boundaries,
STRIDE categories, existing CWE mitigations, CCSDS terminology, and
residual risk discussion.

Issue #53: Camera-ready threat model section.
"""

from pathlib import Path

import pytest

THREAT_MODEL_DOC = Path("docs/15_threat_model.md")


def _read_doc() -> str:
    if not THREAT_MODEL_DOC.is_file():
        pytest.skip(f"{THREAT_MODEL_DOC} not yet created")
    return THREAT_MODEL_DOC.read_text(encoding="utf-8")


# ── Document existence ───────────────────────────────────────────────────


class TestDocumentStructure:
    """The threat model document must exist and have required sections."""

    def test_doc_exists(self):
        assert THREAT_MODEL_DOC.is_file(), (
            f"Threat model document missing: {THREAT_MODEL_DOC}"
        )

    def test_has_trust_boundary_section(self):
        doc = _read_doc()
        assert "Trust Boundar" in doc, "Must have a trust boundary section"

    def test_has_stride_table(self):
        doc = _read_doc()
        assert "STRIDE" in doc, "Must reference STRIDE methodology"

    def test_has_residual_risk_section(self):
        doc = _read_doc()
        assert "Residual Risk" in doc or "residual risk" in doc, (
            "Must discuss residual risks"
        )

    def test_has_ccsds_section(self):
        doc = _read_doc()
        assert "CCSDS" in doc, "Must include CCSDS terminology alignment"


# ── Trust boundaries ─────────────────────────────────────────────────────


class TestTrustBoundaries:
    """All trust boundaries must be documented."""

    @pytest.mark.parametrize("boundary", [
        "YAML",          # User input → compiler
        "OPA",           # Compiler → policy engine
        "rendered",      # Compiler → output artifacts
        "MCP",           # AI agent → MCP server
    ])
    def test_trust_boundary_present(self, boundary: str):
        doc = _read_doc()
        assert boundary.lower() in doc.lower(), (
            f"Trust boundary not documented: {boundary}"
        )


# ── STRIDE categories ───────────────────────────────────────────────────


class TestStrideCategories:
    """All 6 STRIDE categories must appear in the threat analysis."""

    @pytest.mark.parametrize("category", [
        "Spoofing",
        "Tampering",
        "Repudiation",
        "Information Disclosure",
        "Denial of Service",
        "Elevation of Privilege",
    ])
    def test_stride_category_present(self, category: str):
        doc = _read_doc()
        assert category.lower() in doc.lower(), (
            f"STRIDE category not documented: {category}"
        )


# ── Existing CWE mitigations ────────────────────────────────────────────


class TestExistingMitigations:
    """Existing security hardening must be referenced."""

    @pytest.mark.parametrize("cwe", [
        "CWE-22",   # Path traversal
        "CWE-400",  # DoS / timeout
        "CWE-209",  # Information disclosure
        "CWE-502",  # YAML deserialization
    ])
    def test_cwe_referenced(self, cwe: str):
        doc = _read_doc()
        assert cwe in doc, f"Existing mitigation {cwe} not referenced"


# ── Threat IDs ───────────────────────────────────────────────────────────


class TestThreatCoverage:
    """At least 8 specific threats must be documented."""

    def test_minimum_threat_count(self):
        doc = _read_doc()
        # Count rows in threat table (lines starting with | T)
        threat_rows = [line for line in doc.split("\n") if line.strip().startswith("| T") and "|" in line[3:]]
        assert len(threat_rows) >= 8, (
            f"Expected at least 8 threats, found {len(threat_rows)}"
        )


# ── CCSDS terminology ───────────────────────────────────────────────────


class TestCcdsTerminology:
    """CCSDS 522.0-B terminology must be mapped."""

    @pytest.mark.parametrize("term", [
        "Plan Elaboration",
        "Activity Plan",
        "Planning Constraint",
        "522.0",
    ])
    def test_ccsds_term_present(self, term: str):
        doc = _read_doc()
        assert term in doc, f"CCSDS term not documented: {term}"


# ── Standards references ─────────────────────────────────────────────────


class TestStandardsReferences:
    """Space/security standards must be referenced."""

    @pytest.mark.parametrize("standard", [
        "ECSS",
        "CCSDS 350",
    ])
    def test_standard_referenced(self, standard: str):
        doc = _read_doc()
        assert standard in doc, f"Standard not referenced: {standard}"
