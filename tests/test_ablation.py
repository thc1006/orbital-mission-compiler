"""Tests for ablation study framework.

Validates that the mutation corpus covers all error categories and that
schema-only, policy-only, and combined validation produce the expected
detection patterns.

Issue #53: Camera-ready ablation study.
"""

import pytest

from orbital_mission_compiler.ablation import (
    ErrorCategory,
    ValidationArm,
    generate_mutation_corpus,
    run_schema_validation,
    run_policy_validation,
    run_ablation_study,
    format_results_table,
)
from orbital_mission_compiler.policy import opa_available

OPA_AVAILABLE = opa_available()


# ── Corpus completeness ──────────────────────────────────────────────────


class TestMutationCorpus:
    """The mutation corpus must cover all error categories."""

    def test_corpus_is_non_empty(self):
        corpus = generate_mutation_corpus()
        assert len(corpus) > 0

    def test_corpus_covers_all_error_categories(self):
        corpus = generate_mutation_corpus()
        categories = {case["category"] for case in corpus}
        for cat in ErrorCategory:
            assert cat in categories, f"Corpus missing category: {cat.value}"

    def test_corpus_has_valid_plans(self):
        corpus = generate_mutation_corpus()
        valid = [c for c in corpus if c["category"] == ErrorCategory.VALID]
        assert len(valid) >= 2, "Corpus must include at least 2 valid plans"

    def test_each_case_has_required_fields(self):
        corpus = generate_mutation_corpus()
        for case in corpus:
            assert "plan" in case, "Each case must have a 'plan' dict"
            assert "category" in case, "Each case must have a 'category'"
            assert "expected_layer" in case, "Each case must have an 'expected_layer'"
            assert "description" in case, "Each case must have a 'description'"


# ── Schema-only validation ───────────────────────────────────────────────


class TestSchemaValidation:
    """Schema-only validation catches structural errors."""

    def test_detects_empty_mission_id(self):
        corpus = generate_mutation_corpus()
        case = [c for c in corpus if c["category"] == ErrorCategory.EMPTY_MISSION_ID][0]
        detected, _ = run_schema_validation(case["plan"])
        assert detected

    def test_misses_zero_priority(self):
        """Schema allows priority=0; only policy catches this."""
        corpus = generate_mutation_corpus()
        zero_prio = [c for c in corpus if c["category"] == ErrorCategory.ZERO_PRIORITY]
        assert len(zero_prio) >= 1
        detected, _ = run_schema_validation(zero_prio[0]["plan"])
        assert not detected, "Schema should NOT catch zero priority"

    def test_misses_cpu_acceleration(self):
        """Schema has no cross-field constraint for CPU+acceleration."""
        corpus = generate_mutation_corpus()
        cpu_accel = [c for c in corpus if c["category"] == ErrorCategory.CPU_ACCELERATION]
        assert len(cpu_accel) >= 1
        detected, _ = run_schema_validation(cpu_accel[0]["plan"])
        assert not detected, "Schema should NOT catch CPU+acceleration contradiction"

    def test_valid_plan_passes(self):
        corpus = generate_mutation_corpus()
        valid = [c for c in corpus if c["category"] == ErrorCategory.VALID][0]
        detected, _ = run_schema_validation(valid["plan"])
        assert not detected, "Valid plan should pass schema validation"


# ── Policy-only validation ───────────────────────────────────────────────


@pytest.mark.skipif(not OPA_AVAILABLE, reason="OPA CLI not available")
class TestPolicyValidation:
    """Policy-only validation catches semantic errors."""

    def test_detects_zero_priority(self):
        corpus = generate_mutation_corpus()
        zero_prio = [c for c in corpus if c["category"] == ErrorCategory.ZERO_PRIORITY][0]
        detected, _ = run_policy_validation(zero_prio["plan"])
        assert detected

    def test_detects_cpu_acceleration(self):
        corpus = generate_mutation_corpus()
        cpu_accel = [c for c in corpus if c["category"] == ErrorCategory.CPU_ACCELERATION][0]
        detected, _ = run_policy_validation(cpu_accel["plan"])
        assert detected

    def test_misses_acq_without_instrument(self):
        """Policy has no rule requiring instrument on acquisition events."""
        corpus = generate_mutation_corpus()
        no_inst = [c for c in corpus if c["category"] == ErrorCategory.ACQ_NO_INSTRUMENT][0]
        detected, _ = run_policy_validation(no_inst["plan"])
        assert not detected, "Policy should NOT catch missing instrument"

    def test_valid_plan_passes(self):
        corpus = generate_mutation_corpus()
        valid = [c for c in corpus if c["category"] == ErrorCategory.VALID][0]
        detected, _ = run_policy_validation(valid["plan"])
        assert not detected, "Valid plan should pass policy validation"


# ── Combined validation ──────────────────────────────────────────────────


@pytest.mark.skipif(not OPA_AVAILABLE, reason="OPA CLI not available")
class TestCombinedValidation:
    """Combined schema+policy catches all error categories."""

    def test_combined_catches_all_invalid(self):
        corpus = generate_mutation_corpus()
        invalid = [c for c in corpus if c["category"] != ErrorCategory.VALID]
        for case in invalid:
            schema_hit, _ = run_schema_validation(case["plan"])
            policy_hit, _ = run_policy_validation(case["plan"])
            assert schema_hit or policy_hit, (
                f"Combined missed {case['category'].value}: {case['description']}"
            )

    def test_no_false_positives_on_valid(self):
        corpus = generate_mutation_corpus()
        valid = [c for c in corpus if c["category"] == ErrorCategory.VALID]
        for case in valid:
            schema_hit, _ = run_schema_validation(case["plan"])
            policy_hit, _ = run_policy_validation(case["plan"])
            assert not schema_hit and not policy_hit, (
                f"False positive on valid plan: {case['description']}"
            )


# ── Shared fixture (runs ablation once per module) ───────────────────────


@pytest.fixture(scope="module")
def ablation_results():
    """Run the ablation study once and share across all tests in this module."""
    if not OPA_AVAILABLE:
        pytest.skip("OPA CLI not available")
    return run_ablation_study()


# ── Full ablation run ────────────────────────────────────────────────────


@pytest.mark.skipif(not OPA_AVAILABLE, reason="OPA CLI not available")
class TestAblationResults:
    """run_ablation_study produces well-structured results."""

    def test_results_have_all_arms(self, ablation_results):
        for arm in ValidationArm:
            assert arm in ablation_results, f"Results missing arm: {arm.value}"

    def test_results_have_all_categories(self, ablation_results):
        for arm in ValidationArm:
            for cat in ErrorCategory:
                assert cat in ablation_results[arm], (
                    f"Results[{arm.value}] missing category: {cat.value}"
                )

    def test_combined_has_perfect_detection(self, ablation_results):
        for cat in ErrorCategory:
            if cat == ErrorCategory.VALID:
                assert ablation_results[ValidationArm.COMBINED][cat] == 0.0, (
                    f"Combined should have 0% detection on valid plans, "
                    f"got {ablation_results[ValidationArm.COMBINED][cat]}"
                )
            else:
                assert ablation_results[ValidationArm.COMBINED][cat] == 1.0, (
                    f"Combined should catch all {cat.value}, "
                    f"got {ablation_results[ValidationArm.COMBINED][cat]}"
                )


# ── Results formatting ───────────────────────────────────────────────────


@pytest.mark.skipif(not OPA_AVAILABLE, reason="OPA CLI not available")
class TestResultsFormatting:
    """format_results_table outputs a usable markdown table."""

    def test_table_is_string(self, ablation_results):
        table = format_results_table(ablation_results)
        assert isinstance(table, str)

    def test_table_has_header_row(self, ablation_results):
        table = format_results_table(ablation_results)
        assert "Schema" in table
        assert "Policy" in table
        assert "Combined" in table

    def test_table_has_all_categories(self, ablation_results):
        table = format_results_table(ablation_results)
        for cat in ErrorCategory:
            if cat != ErrorCategory.VALID:
                assert cat.value in table, f"Table missing category row: {cat.value}"
