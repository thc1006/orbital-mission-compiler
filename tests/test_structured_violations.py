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


def _canon(viols: list[dict]) -> list:
    """Canonical, occurrence-level comparison key: a SORTED LIST (not a set) of
    the full typed tuple INCLUDING path. Using a list preserves multiplicity, so
    two structurally-identical offenders (which a set would collapse) are caught;
    including path keeps distinct occurrences distinct."""
    # rule may be None (structural guards); map to -1 so mixed lists sort.
    return sorted(
        (
            (-1 if v["rule"] is None else v["rule"]),
            v["rule_id"],
            v["severity"],
            v["provenance"],
            v["path"],
            v["message"],
        )
        for v in viols
    )


def _opa_value(plan: dict) -> dict:
    rc, raw = eval_policy(BUNDLE, plan, DECISION)
    assert rc == 0, f"OPA eval failed (rc={rc}): {raw}"
    return json.loads(raw)["result"][0]["expressions"][0]["value"]


# ── Structured-entry shape ───────────────────────────────────────────────


def test_every_violation_has_the_full_typed_shape():
    seen_rules = set()
    for case in _CORPUS:
        for v in baseline_validator.violations(case["plan"]):
            assert set(v) == {"rule", "rule_id", "severity", "provenance", "path", "message"}
            assert v["severity"] in {"T1", "T2", "T3", "T4"}
            # rule_id is the stable key external consumers match on, so it must
            # agree with the rule number rather than drift from it.
            assert v["rule_id"] == baseline_validator.rule_id(v["rule"])
            assert v["provenance"] in {"A", "D"}
            assert isinstance(v["message"], str) and v["message"]
            assert isinstance(v["path"], str) and v["path"].startswith("/")
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
    opa_viol = _canon(value["violations"])
    py_viol = _canon(baseline_validator.violations(plan))
    assert opa_viol == py_viol, (
        f"structured mismatch on {case['category'].value}:\n"
        f"  only in OPA: {[x for x in opa_viol if x not in py_viol]}\n"
        f"  only in Python: {[x for x in py_viol if x not in opa_viol]}"
    )
    # And deny is still exactly the message projection on both sides.
    assert set(value["deny"]) == set(baseline_validator.evaluate(plan))


# ── Occurrence-level identity: multiplicity + structural fail-closed ─────
# These are the reviewer's counterexamples; each is designed to fail if the
# set-vs-list, Rule-4, or Rego-structural-guard fix regresses.

_ACQ = {"event_type": "acquisition", "instrument": "MSI", "timestamp": "2026-04-15T10:00:00Z",
        "ground_visibility": False}


def _plan(services):
    return {"mission_id": "m", "events": [dict(_ACQ, services=services)]}


def test_duplicate_offenders_are_distinct_occurrences():
    # Two services with the SAME id + priority 0 -> TWO Rule-5 violations, not one.
    # A set-collapsing comparison (or a message-level Rego set without path) would
    # wrongly report a single violation.
    plan = _plan([
        {"service_id": "dup", "priority": 0, "steps": [{"name": "a", "resource_class": "cpu"}]},
        {"service_id": "dup", "priority": 0, "steps": [{"name": "a", "resource_class": "cpu"}]},
    ])
    r5 = [v for v in baseline_validator.violations(plan) if v["rule"] == 5]
    assert len(r5) == 2
    assert {v["path"] for v in r5} == {"/events/0/services/0", "/events/0/services/1"}


@pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")
def test_duplicate_offenders_match_opa_multiplicity():
    plan = _plan([
        {"service_id": "dup", "priority": 0, "steps": [{"name": "a", "resource_class": "cpu"}]},
        {"service_id": "dup", "priority": 0, "steps": [{"name": "a", "resource_class": "cpu"}]},
    ])
    assert _canon(_opa_value(plan)["violations"]) == _canon(baseline_validator.violations(plan))


def test_rule4_rejects_fallback_equal_to_primary():
    # A "fallback" equal to the primary class is not a real fallback.
    plan = _plan([{"service_id": "s", "priority": 50,
                   "steps": [{"name": "g", "resource_class": "gpu", "fallback_resource_class": "gpu"}]}])
    r4 = [v for v in baseline_validator.violations(plan) if v["rule"] == 4]
    assert len(r4) == 1 and "usable fallback" in r4[0]["message"]
    assert not baseline_validator.is_allowed(plan)


@pytest.mark.parametrize("bad_events", [None, "not-a-list"], ids=["missing", "non-list"])
def test_structural_bypass_is_denied(bad_events):
    # Raw-JSON bypass path: malformed `events` must fail closed in the baseline.
    plan = {"mission_id": "m"} if bad_events is None else {"mission_id": "m", "events": bad_events}
    assert not baseline_validator.is_allowed(plan)


@pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")
@pytest.mark.parametrize("bad_events", [None, "not-a-list"], ids=["missing", "non-list"])
def test_structural_bypass_denied_by_opa_too(bad_events):
    # The Rego policy must ALSO fail closed on the bypass path (it previously
    # allowed a missing `events` key because count(undefined) is undefined).
    plan = {"mission_id": "m"} if bad_events is None else {"mission_id": "m", "events": bad_events}
    assert _opa_value(plan)["allow"] is False


# ── Raw-JSON / language-seam edge cases (adversarial-review counterexamples) ─
# These are inputs where the two engines historically diverged because of
# language-specific truthiness/absence/coercion rules (Rego: reference to an
# absent key vanishes the rule, only false/undefined are falsy; Python: `or []`,
# `not`, `False == 0`). They must now agree on BOTH the decision and the full
# typed violation list. The corpus alone (well-formed single-rule mutations) does
# not exercise these, so they are enumerated explicitly.

def _acq(services):
    return {"mission_id": "m", "events": [dict(_ACQ, services=services)]}


_EDGE_CASES = {
    "rule4-gpu-no-name": _acq([{"service_id": "s", "priority": 1, "steps": [{"resource_class": "gpu"}]}]),
    "rule5-priority0-no-sid": _acq([{"priority": 0, "steps": [{"resource_class": "cpu", "name": "x"}]}]),
    "rule9-nosteps-no-sid": _acq([{"priority": 1, "steps": []}]),
    "rule10-badland-no-sid": _acq([{"priority": 1, "landscape_type": "desert",
                                    "steps": [{"resource_class": "cpu", "name": "x"}]}]),
    "rule8-gv-zero": {"mission_id": "m", "events": [{"event_type": "download", "ground_visibility": 0}]},
    "rule8-gv-null": {"mission_id": "m", "events": [{"event_type": "download", "ground_visibility": None}]},
    "rule8-gv-empty": {"mission_id": "m", "events": [{"event_type": "download", "ground_visibility": ""}]},
    "services-falsy-scalar": {"mission_id": "m", "events": [{"event_type": "other", "services": 0}]},
    "steps-falsy-scalar": _acq([{"service_id": "s", "priority": 1, "steps": 0}]),
    "priority-false-not-zero": _acq([{"service_id": "s", "priority": False,
                                      "steps": [{"resource_class": "cpu", "name": "x"}]}]),
    "rule4-nonstring-fallback": _acq([{"service_id": "s", "priority": 1,
                                       "steps": [{"name": "g", "resource_class": "gpu",
                                                  "fallback_resource_class": 123}]}]),
}


@pytest.mark.parametrize("plan", list(_EDGE_CASES.values()), ids=list(_EDGE_CASES))
def test_edge_case_baseline_decision_is_stable(plan):
    # Baseline decision is deterministic (no crash) on each pathological input.
    assert isinstance(baseline_validator.is_allowed(plan), bool)


@pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")
@pytest.mark.parametrize("plan", list(_EDGE_CASES.values()), ids=list(_EDGE_CASES))
def test_edge_case_engines_agree(plan):
    value = _opa_value(plan)
    # Decision equivalence on every seam input.
    assert (not value["allow"]) == (not baseline_validator.is_allowed(plan))
    # And the full typed violation list is identical (canonical, incl path).
    assert _canon(value["violations"]) == _canon(baseline_validator.violations(plan))


# ── Second-review seams: JSON null, independent-rule evaluation, escaping ────
# F1: a present `null` services/steps previously made the OPA engine fail OPEN
#     (rule vanished) while the baseline denied. F2: a malformed steps made the
#     baseline over-suppress independent rules (priority/landscape). F3: control/
#     quote chars in identifiers diverged the message. All three must now agree.

_SEAM2_CASES = {
    "services-null-acq": _acq(None),
    "steps-null": _acq([{"service_id": "s", "priority": 1, "steps": None}]),
    "services-null-visible-download": {"mission_id": "m", "events": [
        {"event_type": "download", "ground_visibility": True, "services": None}]},
    "malformed-steps-keeps-priority+landscape": _acq([
        {"service_id": "s", "priority": 0, "landscape_type": "desert", "steps": "x"}]),
    "malformed-services-keeps-visibility": {"mission_id": "m", "events": [
        {"event_type": "download", "services": 0}]},
    "sid-backslash": _acq([{"service_id": "a\\b", "priority": 0,
                            "steps": [{"name": "a", "resource_class": "cpu"}]}]),
    "sid-quote": _acq([{"service_id": 'q"t', "priority": 0,
                        "steps": [{"name": "a", "resource_class": "cpu"}]}]),
    "sid-tab-newline-cr": _acq([{"service_id": "a\tb\nc\rd", "priority": 0,
                                 "steps": [{"name": "a", "resource_class": "cpu"}]}]),
    "name-unicode": _acq([{"service_id": "s", "priority": 1,
                           "steps": [{"name": "g\U0001F600é", "resource_class": "gpu"}]}]),
    "nonstring-fallback-quote-name": _acq([{"service_id": "s", "priority": 1, "steps": [
        {"name": 'x"y', "resource_class": "gpu", "fallback_resource_class": 123}]}]),
}


def test_null_container_fires_emptiness_rule_baseline():
    # F1: services:null / steps:null are treated as empty -> Rule 3 / Rule 9 fire
    # (they must NOT silently pass as they once did in the authoritative engine).
    assert any(v["rule"] == 3 for v in baseline_validator.violations(_acq(None)))
    steps_null = _acq([{"service_id": "s", "priority": 1, "steps": None}])
    assert any(v["rule"] == 9 for v in baseline_validator.violations(steps_null))


def test_malformed_steps_does_not_suppress_independent_rules():
    # F2: a non-list steps must NOT hide the priority (5) or landscape (10) checks;
    # the structural guard (rule None) is reported alongside them.
    plan = _acq([{"service_id": "s", "priority": 0, "landscape_type": "desert", "steps": "x"}])
    rules = {v["rule"] for v in baseline_validator.violations(plan)}
    assert {5, 10, None} <= rules


@pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")
@pytest.mark.parametrize("plan", list(_SEAM2_CASES.values()), ids=list(_SEAM2_CASES))
def test_seam2_engines_agree(plan):
    value = _opa_value(plan)
    assert (not value["allow"]) == (not baseline_validator.is_allowed(plan))
    assert _canon(value["violations"]) == _canon(baseline_validator.violations(plan))
