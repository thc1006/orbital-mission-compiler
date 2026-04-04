"""Corpus completeness tests for mission plans.

Verifies that the mission plan corpus has sufficient size and diversity
to serve as a representative test suite for the compiler pipeline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orbital_mission_compiler.compiler import load_mission_plan, compile_plan_to_intents
from orbital_mission_compiler.eval_runner import _discover_cases, _run_case

_REPO_ROOT = Path(__file__).resolve().parent.parent
PLANS_DIR = _REPO_ROOT / "configs" / "mission_plans"
GOLDEN_DIR = _REPO_ROOT / "evals" / "golden"

# ---------------------------------------------------------------------------
# Discover all plans once (avoid repeated filesystem + YAML parsing per test)
# ---------------------------------------------------------------------------

_ALL_PLAN_PATHS = sorted(PLANS_DIR.glob("*.yaml"))


def _plan_ids() -> list[str]:
    return [p.stem for p in _ALL_PLAN_PATHS]


# ---------------------------------------------------------------------------
# 1. Every plan loads and validates successfully
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("plan_path", _ALL_PLAN_PATHS, ids=_plan_ids())
def test_plan_loads_successfully(plan_path: Path) -> None:
    """Each YAML plan must parse and pass Pydantic schema validation."""
    plan = load_mission_plan(plan_path)
    assert plan.mission_id, f"{plan_path.name}: mission_id must not be empty"
    assert len(plan.events) >= 1, f"{plan_path.name}: must have at least 1 event"


# ---------------------------------------------------------------------------
# 2. Every plan compiles to at least 1 workflow intent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("plan_path", _ALL_PLAN_PATHS, ids=_plan_ids())
def test_plan_compiles_to_intents(plan_path: Path) -> None:
    """Each plan with acquisition events must produce at least 1 WorkflowIntent."""
    plan = load_mission_plan(plan_path)
    intents = compile_plan_to_intents(plan)
    acq_count = sum(
        1 for ev in plan.events if ev.event_type.value == "acquisition" and ev.services
    )
    assert len(intents) >= 1, (
        f"{plan_path.name}: expected at least 1 intent from {acq_count} acquisition event(s)"
    )


# ---------------------------------------------------------------------------
# 3. Every plan with a golden eval passes the eval runner
# ---------------------------------------------------------------------------


def test_all_golden_evals_pass() -> None:
    """All golden eval files must match current compiler output exactly."""
    cases, orphans = _discover_cases()
    assert not orphans, (
        f"Orphan golden files with no matching plan: {[o.name for o in orphans]}"
    )
    assert len(cases) >= 1, "No golden eval cases discovered"

    failures = []
    for mission, golden in cases:
        ok, msg = _run_case(mission, golden)
        if not ok:
            failures.append(mission.name)

    assert not failures, (
        f"Golden eval mismatches for: {failures}. "
        "Re-generate with: PYTHONPATH=src:. python3 scripts/run_eval.sh"
    )


# ---------------------------------------------------------------------------
# 4. Corpus has at least 10 plans
# ---------------------------------------------------------------------------


def test_corpus_minimum_size() -> None:
    """Issue #53 requires 10-20 domain-expert-annotated mission plans."""
    assert len(_ALL_PLAN_PATHS) >= 10, (
        f"Corpus has only {len(_ALL_PLAN_PATHS)} plans, need at least 10"
    )


# ---------------------------------------------------------------------------
# 5. Plans cover diverse resource classes (CPU, GPU, FPGA)
# ---------------------------------------------------------------------------


def test_corpus_covers_resource_classes() -> None:
    """The corpus must exercise CPU, GPU, and FPGA resource classes."""
    observed_classes: set[str] = set()
    for plan_path in _ALL_PLAN_PATHS:
        plan = load_mission_plan(plan_path)
        intents = compile_plan_to_intents(plan)
        for intent in intents:
            for step in intent.steps:
                observed_classes.add(step.resource_class.value)

    required = {"cpu", "gpu", "fpga"}
    missing = required - observed_classes
    assert not missing, (
        f"Resource classes not covered by any plan: {missing}. "
        f"Observed: {observed_classes}"
    )


# ---------------------------------------------------------------------------
# 6. Plans cover both execution modes (sequential, parallel)
# ---------------------------------------------------------------------------


def test_corpus_covers_execution_modes() -> None:
    """The corpus must exercise both sequential and parallel execution modes."""
    observed_modes: set[str] = set()
    for plan_path in _ALL_PLAN_PATHS:
        plan = load_mission_plan(plan_path)
        intents = compile_plan_to_intents(plan)
        for intent in intents:
            mode = intent.resource_hints.get("execution_mode", "sequential")
            observed_modes.add(mode)

    required = {"sequential", "parallel"}
    missing = required - observed_modes
    assert not missing, (
        f"Execution modes not covered by any plan: {missing}. "
        f"Observed: {observed_modes}"
    )


# ---------------------------------------------------------------------------
# 7. Plans cover both landscape types (ocean, land)
# ---------------------------------------------------------------------------


def test_corpus_covers_landscape_types() -> None:
    """The corpus should exercise both ocean and land landscape types."""
    observed_types: set[str] = set()
    for plan_path in _ALL_PLAN_PATHS:
        plan = load_mission_plan(plan_path)
        intents = compile_plan_to_intents(plan)
        for intent in intents:
            lt = intent.resource_hints.get("landscape_type")
            if lt is not None:
                observed_types.add(lt)

    required = {"ocean", "land"}
    missing = required - observed_types
    assert not missing, (
        f"Landscape types not covered by any plan: {missing}. "
        f"Observed: {observed_types}"
    )


# ---------------------------------------------------------------------------
# 8. Every golden eval file has a corresponding plan
# ---------------------------------------------------------------------------


def test_golden_eval_coverage() -> None:
    """Every plan in the corpus should have a golden eval file."""
    plans_with_evals = {
        g.name.removesuffix(".expected.json")
        for g in GOLDEN_DIR.glob("*.expected.json")
    }
    plans_without_evals = [
        p.stem for p in _ALL_PLAN_PATHS if p.stem not in plans_with_evals
    ]
    assert not plans_without_evals, (
        f"Plans missing golden evals: {plans_without_evals}. "
        "Generate with the eval generation script."
    )
