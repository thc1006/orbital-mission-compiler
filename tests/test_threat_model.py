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
        assert "Trust Boundaries" in doc, "Must have a Trust Boundaries section"

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
    """All 4 trust boundaries (TB1-TB4) must be documented."""

    @pytest.mark.parametrize("boundary_id", ["TB1", "TB2", "TB3", "TB4"])
    def test_trust_boundary_present(self, boundary_id: str):
        doc = _read_doc()
        assert boundary_id in doc, (
            f"Trust boundary not documented: {boundary_id}"
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
    """All 6 existing CWE mitigations must be referenced."""

    @pytest.mark.parametrize("cwe", [
        "CWE-22",   # Path traversal
        "CWE-209",  # Information disclosure
        "CWE-250",  # Unnecessary privileges
        "CWE-377",  # Insecure temporary file
        "CWE-400",  # DoS / timeout
        "CWE-502",  # YAML deserialization
    ])
    def test_cwe_referenced(self, cwe: str):
        doc = _read_doc()
        assert cwe in doc, f"Existing mitigation {cwe} not referenced"


# ── Threat IDs ───────────────────────────────────────────────────────────


class TestThreatCoverage:
    """All 10 threats (T1-T10) must be documented."""

    def test_all_ten_threats_present_and_unique(self):
        doc = _read_doc()
        found_ids = []
        for line in doc.splitlines():
            parts = line.strip().split("|")
            if len(parts) >= 3:
                cell = parts[1].strip()
                if cell.startswith("T") and cell[1:].isdigit():
                    found_ids.append(cell)
        required = {f"T{i}" for i in range(1, 11)}
        missing = sorted(required - set(found_ids))
        assert not missing, f"Missing threats: {missing}"
        duplicates = sorted(t for t in required if found_ids.count(t) > 1)
        assert not duplicates, f"Duplicate threats: {duplicates}"


# ── CCSDS terminology ───────────────────────────────────────────────────


class TestCcsdsTerminology:
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
