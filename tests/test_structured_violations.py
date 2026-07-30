"""Effective tests for structured policy output (P2-8).

The policy layer now emits typed violations -- ``{rule, severity, provenance,
message}`` -- instead of opaque deny strings, so a consumer can triage by the
paper's loss-event severity tier (T1-T4) and provenance (A = author-imposed,
D = ORCHIDE-derived) without re-parsing prose.

Every test here is designed to FAIL on a real regression:

- ``PAPER_TABLE_III`` is the authoritative severity/provenance mapping copied
  from the frozen paper's Table III. It is deliberately NOT imported from the
  implementation's own ``_RULE_META`` -- it is the independent ground truth the
  implementation must satisfy, so mislabelling any rule's tier or provenance in
  either the Python baseline or the Rego policy fails a test here.
- The Python baseline and the OPA/Rego policy must emit IDENTICAL structured
  violations on every corpus plan (proves the two layers agree not just on
  accept/reject but on the full typed decision).
- ``evaluate()`` must stay the exact message projection of ``violations()`` and
  equal to the OPA ``deny`` set (proves the refactor kept deny byte-identical).
"""

import json

import pytest

from orbital_mission_compiler import baseline_validator
from orbital_mission_compiler.ablation import ErrorCategory, generate_mutation_corpus
from orbital_mission_compiler.policy import eval_policy, opa_available

BUNDLE = "configs/policies"
DECISION = "data.orbitalmission"

# Ground truth from the paper's Table III (Pre-Uplink Loss-Event Severity
# Tiers) + its provenance footnote. Independent of the implementation.
PAPER_TABLE_III: dict[int, tuple[str, str]] = {
    1: ("T1", "A"),
    2: ("T1", "A"),
    3: ("T4", "D"),
    4: ("T2", "A"),
    5: ("T4", "A"),
    6: ("T2", "A"),
    7: ("T3", "D"),
    8: ("T3", "D"),
    9: ("T4", "A"),
    10: ("T4", "D"),
}

# Each corpus category deterministically triggers one specific deny rule.
CATEGORY_TO_RULE: dict[ErrorCategory, int] = {
    ErrorCategory.EMPTY_MISSION_ID: 1,
    ErrorCategory.EMPTY_EVENTS: 2,
    ErrorCategory.ACQ_NO_SERVICES: 3,
    ErrorCategory.GPU_NO_FALLBACK: 4,
    ErrorCategory.ZERO_PRIORITY: 5,
    ErrorCategory.CPU_ACCELERATION: 6,
    ErrorCategory.DOWNLOAD_WITH_SERVICES: 7,
    ErrorCategory.DOWNLOAD_NO_VISIBILITY: 8,
    ErrorCategory.SERVICE_NO_STEPS: 9,
    ErrorCategory.INVALID_LANDSCAPE: 10,
}

_CORPUS = generate_mutation_corpus()


def _plan_for(category: ErrorCategory) -> dict:
    for case in _CORPUS:
        if case["category"] == category:
            return case["plan"]
    raise AssertionError(f"category {category} not in corpus")


def _tuples(viols: list[dict]) -> set:
    return {(v["rule"], v["severity"], v["provenance"], v["message"]) for v in viols}


def _opa_value(plan: dict) -> dict:
    rc, raw = eval_policy(BUNDLE, plan, DECISION)
    assert rc == 0, f"OPA eval failed (rc={rc}): {raw}"
    return json.loads(raw)["result"][0]["expressions"][0]["value"]


# ── Structured-entry shape ───────────────────────────────────────────────


def test_every_violation_has_the_full_typed_shape():
    seen_rules = set()
    for case in _CORPUS:
        for v in baseline_validator.violations(case["plan"]):
            assert set(v) == {"rule", "severity", "provenance", "message"}
            assert v["severity"] in {"T1", "T2", "T3", "T4"}
            assert v["provenance"] in {"A", "D"}
            assert isinstance(v["message"], str) and v["message"]
            if v["rule"] is not None:
                seen_rules.add(v["rule"])
    # The corpus must actually exercise all ten rules, else the mapping tests
    # below would silently skip a rule's metadata.
    assert seen_rules == set(range(1, 11))


# ── Severity/provenance matches the paper (independent ground truth) ─────


@pytest.mark.parametrize("category, rule", sorted(CATEGORY_TO_RULE.items(), key=lambda kv: kv[1]))
def test_severity_provenance_matches_paper_table_iii(category: ErrorCategory, rule: int):
    plan = _plan_for(category)
    matched = [v for v in baseline_validator.violations(plan) if v["rule"] == rule]
    assert matched, f"{category.value} did not trigger rule {rule}"
    exp_sev, exp_prov = PAPER_TABLE_III[rule]
    for v in matched:
        assert (v["severity"], v["provenance"]) == (exp_sev, exp_prov), (
            f"rule {rule} mislabelled: got ({v['severity']},{v['provenance']}), "
            f"paper Table III says ({exp_sev},{exp_prov})"
        )


# ── evaluate() is the message projection; deny stays byte-identical ──────


def test_evaluate_is_exact_message_projection_of_violations():
    for case in _CORPUS:
        plan = case["plan"]
        assert baseline_validator.evaluate(plan) == [
            v["message"] for v in baseline_validator.violations(plan)
        ]


# ── Python baseline and OPA/Rego must agree on the FULL typed decision ───


@pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")
@pytest.mark.parametrize(
    "case", _CORPUS, ids=[f"{i}-{c['category'].value}" for i, c in enumerate(_CORPUS)]
)
def test_opa_structured_violations_match_python(case):
    plan = case["plan"]
    value = _opa_value(plan)
    opa_viol = _tuples(value["violations"])
    py_viol = _tuples(baseline_validator.violations(plan))
    assert opa_viol == py_viol, (
        f"structured mismatch on {case['category'].value}:\n"
        f"  only in OPA: {opa_viol - py_viol}\n"
        f"  only in Python: {py_viol - opa_viol}"
    )
    # And deny is still exactly the message projection on both sides.
    assert set(value["deny"]) == set(baseline_validator.evaluate(plan))
