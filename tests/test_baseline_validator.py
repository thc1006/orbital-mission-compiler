"""Equivalence + unit tests for the in-process Python baseline validator.

The key test proves that ``baseline_validator`` makes the SAME accept/reject
decision as the OPA/Rego policy on the full ablation mutation corpus, so it is a
faithful performance baseline for the OPA-vs-in-process comparison in Section V-B.
"""

import json

import pytest

from orbital_mission_compiler import baseline_validator
from orbital_mission_compiler.ablation import generate_mutation_corpus
from orbital_mission_compiler.policy import eval_policy, opa_available

BUNDLE = "configs/policies"
DECISION = "data.orbitalmission"

_CORPUS = generate_mutation_corpus()


def _opa_allowed(plan: dict) -> bool:
    rc, raw = eval_policy(BUNDLE, plan, DECISION)
    assert rc == 0, f"OPA eval failed (rc={rc}): {raw}"
    value = json.loads(raw)["result"][0]["expressions"][0]["value"]
    return bool(value["allow"])


# ── Equivalence with OPA over the full corpus ────────────────────────────


@pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")
@pytest.mark.parametrize(
    "case",
    _CORPUS,
    ids=[f"{i}-{c['category'].value}" for i, c in enumerate(_CORPUS)],
)
def test_baseline_matches_opa_decision(case):
    """Baseline and OPA must agree on allow/deny for every corpus plan."""
    plan = case["plan"]
    baseline_allowed = baseline_validator.is_allowed(plan)
    opa_allowed = _opa_allowed(plan)
    assert baseline_allowed == opa_allowed, (
        f"decision mismatch on {case['category'].value}: "
        f"baseline_allowed={baseline_allowed}, opa_allowed={opa_allowed}, "
        f"baseline denies={baseline_validator.evaluate(plan)}"
    )


# ── Direct unit tests (run without OPA) ──────────────────────────────────


def test_valid_plan_allowed():
    from orbital_mission_compiler.benchmark import generate_synthetic_plan

    assert baseline_validator.is_allowed(generate_synthetic_plan(5)) is True


def test_gpu_without_fallback_denied():
    plan = {
        "mission_id": "m",
        "events": [
            {
                "event_type": "acquisition",
                "services": [
                    {
                        "service_id": "s",
                        "priority": 50,
                        "steps": [{"name": "g", "resource_class": "gpu"}],
                    }
                ],
            }
        ],
    }
    assert baseline_validator.is_allowed(plan) is False
    assert any("fallback_resource_class" in m for m in baseline_validator.evaluate(plan))


def test_null_landscape_allowed_but_invalid_denied():
    base = {
        "mission_id": "m",
        "events": [
            {
                "event_type": "acquisition",
                "services": [
                    {
                        "service_id": "s",
                        "priority": 50,
                        "landscape_type": None,
                        "steps": [{"name": "c", "resource_class": "cpu"}],
                    }
                ],
            }
        ],
    }
    assert baseline_validator.is_allowed(base) is True  # null permitted
    bad = json.loads(json.dumps(base))
    bad["events"][0]["services"][0]["landscape_type"] = "desert"
    assert baseline_validator.is_allowed(bad) is False  # present-invalid denied
    worse = json.loads(json.dumps(base))
    worse["events"][0]["services"][0]["landscape_type"] = 42
    assert baseline_validator.is_allowed(worse) is False  # non-string denied
