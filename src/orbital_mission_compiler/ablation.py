"""Ablation study framework: schema-only vs policy-only vs combined validation.

Generates a mutation corpus of invalid mission plans, runs each through
three validation arms, and reports per-category detection rates.

Issue #53: Camera-ready ablation study.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import ValidationError

from .policy import eval_policy, opa_available
from .schemas import MissionPlan


class ErrorCategory(str, Enum):
    """Error categories for the mutation corpus."""

    VALID = "valid"
    # Schema-only (Pydantic catches, OPA does not)
    ACQ_NO_INSTRUMENT = "acq_no_instrument"
    DOWNLOAD_NO_DURATION = "download_no_duration"
    # Policy-only (OPA catches, Pydantic does not)
    ACQ_NO_SERVICES = "acq_no_services"
    GPU_NO_FALLBACK = "gpu_no_fallback"
    ZERO_PRIORITY = "zero_priority"
    CPU_ACCELERATION = "cpu_acceleration"
    INVALID_LANDSCAPE = "invalid_landscape"
    # Both layers (defense-in-depth overlap)
    EMPTY_MISSION_ID = "empty_mission_id"
    EMPTY_EVENTS = "empty_events"
    DOWNLOAD_WITH_SERVICES = "download_with_services"
    DOWNLOAD_NO_VISIBILITY = "download_no_visibility"
    SERVICE_NO_STEPS = "service_no_steps"


class ValidationArm(str, Enum):
    SCHEMA = "schema"
    POLICY = "policy"
    COMBINED = "combined"


# ── Mutation corpus ──────────────────────────────────────────────────────

_VALID_STEP = {
    "name": "detect",
    "image": "busybox:1.36",
    "resource_class": "cpu",
    "command": ["sh", "-c"],
    "args": ["echo ok"],
}

_VALID_GPU_STEP = {
    "name": "gpu-detect",
    "image": "nvcr.io/nvidia/pytorch:24.01-py3",
    "resource_class": "gpu",
    "needs_acceleration": True,
    "fallback_resource_class": "cpu",
}

_VALID_SERVICE = {
    "service_id": "ship-detection",
    "priority": 50,
    "landscape_type": "ocean",
    "execution_mode": "sequential",
    "steps": [_VALID_STEP],
}

_VALID_ACQ_EVENT = {
    "timestamp": "2026-04-15T10:00:00Z",
    "event_type": "acquisition",
    "orbit": 1,
    "instrument": "MSI",
    "ground_visibility": False,
    "services": [_VALID_SERVICE],
}

_VALID_DOWNLOAD_EVENT = {
    "timestamp": "2026-04-15T11:00:00Z",
    "event_type": "download",
    "orbit": 2,
    "duration_seconds": 300.0,
    "ground_visibility": True,
}


def _base_plan() -> dict[str, Any]:
    """Return a structurally valid mission plan dict."""
    return {
        "mission_id": "ablation-test",
        "events": [_deep_copy(_VALID_ACQ_EVENT)],
    }


def _deep_copy(obj: Any) -> Any:
    """Simple deep copy for JSON-serializable dicts/lists."""
    return json.loads(json.dumps(obj))


def generate_mutation_corpus() -> list[dict[str, Any]]:
    """Generate a corpus of valid and invalid mission plans for ablation study."""
    corpus: list[dict[str, Any]] = []

    # ── Valid plans ──────────────────────────────────────────────────
    corpus.append({
        "plan": _base_plan(),
        "category": ErrorCategory.VALID,
        "expected_layer": "none",
        "description": "Valid single-ACQ plan with CPU service",
    })

    plan_with_download = _base_plan()
    plan_with_download["events"].append(_deep_copy(_VALID_DOWNLOAD_EVENT))
    corpus.append({
        "plan": plan_with_download,
        "category": ErrorCategory.VALID,
        "expected_layer": "none",
        "description": "Valid plan with ACQ + DOWNLOAD events",
    })

    # ── Schema-only errors ───────────────────────────────────────────

    # ACQ without instrument
    p = _base_plan()
    del p["events"][0]["instrument"]
    corpus.append({
        "plan": p,
        "category": ErrorCategory.ACQ_NO_INSTRUMENT,
        "expected_layer": "schema",
        "description": "Acquisition event missing instrument (slide 9: INST)",
    })

    # DOWNLOAD without duration
    p = _base_plan()
    p["events"] = [{"timestamp": "2026-04-15T11:00:00Z", "event_type": "download",
                     "orbit": 2, "ground_visibility": True}]
    corpus.append({
        "plan": p,
        "category": ErrorCategory.DOWNLOAD_NO_DURATION,
        "expected_layer": "schema",
        "description": "Download event missing duration_seconds (slide 9: DT_EV)",
    })

    # ── Policy-only errors ───────────────────────────────────────────

    # ACQ with zero services
    p = _base_plan()
    p["events"][0]["services"] = []
    corpus.append({
        "plan": p,
        "category": ErrorCategory.ACQ_NO_SERVICES,
        "expected_layer": "policy",
        "description": "Acquisition event with no services (slide 9: WORKFLOW required)",
    })

    # GPU step without fallback
    p = _base_plan()
    gpu_step = _deep_copy(_VALID_GPU_STEP)
    del gpu_step["fallback_resource_class"]
    p["events"][0]["services"][0]["steps"] = [gpu_step]
    corpus.append({
        "plan": p,
        "category": ErrorCategory.GPU_NO_FALLBACK,
        "expected_layer": "policy",
        "description": "GPU+acceleration step without fallback_resource_class",
    })

    # Zero priority
    p = _base_plan()
    p["events"][0]["services"][0]["priority"] = 0
    corpus.append({
        "plan": p,
        "category": ErrorCategory.ZERO_PRIORITY,
        "expected_layer": "policy",
        "description": "Service priority=0 (misconfiguration; ORCHIDE uses 1-4)",
    })

    # CPU + needs_acceleration
    p = _base_plan()
    p["events"][0]["services"][0]["steps"] = [{
        "name": "cpu-accel",
        "image": "busybox:1.36",
        "resource_class": "cpu",
        "needs_acceleration": True,
    }]
    corpus.append({
        "plan": p,
        "category": ErrorCategory.CPU_ACCELERATION,
        "expected_layer": "policy",
        "description": "CPU step with needs_acceleration=true (contradiction)",
    })

    # Invalid landscape_type
    p = _base_plan()
    p["events"][0]["services"][0]["landscape_type"] = "desert"
    corpus.append({
        "plan": p,
        "category": ErrorCategory.INVALID_LANDSCAPE,
        "expected_layer": "policy",
        "description": "Unrecognized landscape_type 'desert' (slide 9: O/L only)",
    })

    # ── Both-layer errors (defense-in-depth) ─────────────────────────

    # Empty mission_id
    p = _base_plan()
    p["mission_id"] = ""
    corpus.append({
        "plan": p,
        "category": ErrorCategory.EMPTY_MISSION_ID,
        "expected_layer": "both",
        "description": "Empty mission_id",
    })

    # Empty events
    p = _base_plan()
    p["events"] = []
    corpus.append({
        "plan": p,
        "category": ErrorCategory.EMPTY_EVENTS,
        "expected_layer": "both",
        "description": "Mission plan with zero events",
    })

    # DOWNLOAD with services
    p = _base_plan()
    p["events"] = [{
        "timestamp": "2026-04-15T11:00:00Z",
        "event_type": "download",
        "orbit": 2,
        "duration_seconds": 300.0,
        "ground_visibility": True,
        "services": [_deep_copy(_VALID_SERVICE)],
    }]
    corpus.append({
        "plan": p,
        "category": ErrorCategory.DOWNLOAD_WITH_SERVICES,
        "expected_layer": "both",
        "description": "Download event carrying AI services (slide 9: DOWNLOAD has no WORKFLOW)",
    })

    # DOWNLOAD without visibility
    p = _base_plan()
    p["events"] = [{
        "timestamp": "2026-04-15T11:00:00Z",
        "event_type": "download",
        "orbit": 2,
        "duration_seconds": 300.0,
        "ground_visibility": False,
    }]
    corpus.append({
        "plan": p,
        "category": ErrorCategory.DOWNLOAD_NO_VISIBILITY,
        "expected_layer": "both",
        "description": "Download event without ground visibility (slide 9: VISI=1)",
    })

    # Service with no steps
    p = _base_plan()
    p["events"][0]["services"][0]["steps"] = []
    corpus.append({
        "plan": p,
        "category": ErrorCategory.SERVICE_NO_STEPS,
        "expected_layer": "both",
        "description": "Service with zero steps",
    })

    return corpus


# ── Validation arms ──────────────────────────────────────────────────────

POLICY_BUNDLE = "configs/policies"
POLICY_DECISION = "data.orbitalmission"


def run_schema_validation(plan_dict: dict[str, Any]) -> tuple[bool, str]:
    """Run Pydantic schema validation only. Returns (detected, error_message)."""
    try:
        MissionPlan.model_validate(plan_dict)
        return False, ""
    except (ValidationError, ValueError) as exc:
        return True, str(exc)


def run_policy_validation(plan_dict: dict[str, Any]) -> tuple[bool, list[str]]:
    """Run OPA policy validation only (skips schema). Returns (detected, deny_messages)."""
    if not opa_available():
        return False, ["opa CLI not available"]
    rc, output = eval_policy(POLICY_BUNDLE, plan_dict, POLICY_DECISION)
    if rc != 0:
        return False, [f"OPA error (rc={rc}): {output}"]
    try:
        parsed = json.loads(output)
        result = parsed["result"][0]["expressions"][0]["value"]
        deny = result.get("deny", [])
        return len(deny) > 0, deny
    except (json.JSONDecodeError, KeyError, IndexError):
        return False, [f"Unparseable OPA output: {output[:200]}"]


# ── Ablation runner ──────────────────────────────────────────────────────


def run_ablation_study() -> dict[ValidationArm, dict[ErrorCategory, float]]:
    """Run the full three-arm ablation study.

    Returns detection rates per (arm, category). For valid plans the rate
    represents false positives (should be 0.0).
    """
    corpus = generate_mutation_corpus()

    # Group by category
    by_category: dict[ErrorCategory, list[dict]] = {}
    for case in corpus:
        by_category.setdefault(case["category"], []).append(case)

    results: dict[ValidationArm, dict[ErrorCategory, float]] = {
        arm: {} for arm in ValidationArm
    }

    for cat, cases in by_category.items():
        n = len(cases)
        schema_hits = 0
        policy_hits = 0
        combined_hits = 0

        for case in cases:
            s_det, _ = run_schema_validation(case["plan"])
            p_det, _ = run_policy_validation(case["plan"])

            if s_det:
                schema_hits += 1
            if p_det:
                policy_hits += 1
            if s_det or p_det:
                combined_hits += 1

        results[ValidationArm.SCHEMA][cat] = schema_hits / n
        results[ValidationArm.POLICY][cat] = policy_hits / n
        results[ValidationArm.COMBINED][cat] = combined_hits / n

    return results


# ── Results formatting ───────────────────────────────────────────────────


def format_results_table(
    results: dict[ValidationArm, dict[ErrorCategory, float]],
) -> str:
    """Format ablation results as a markdown table suitable for the paper."""
    lines = [
        "| Error Category | Layer | Schema | Policy | Combined |",
        "|---|---|---|---|---|",
    ]

    layer_map = {
        ErrorCategory.ACQ_NO_INSTRUMENT: "Schema-only",
        ErrorCategory.DOWNLOAD_NO_DURATION: "Schema-only",
        ErrorCategory.ACQ_NO_SERVICES: "Policy-only",
        ErrorCategory.GPU_NO_FALLBACK: "Policy-only",
        ErrorCategory.ZERO_PRIORITY: "Policy-only",
        ErrorCategory.CPU_ACCELERATION: "Policy-only",
        ErrorCategory.INVALID_LANDSCAPE: "Policy-only",
        ErrorCategory.EMPTY_MISSION_ID: "Both",
        ErrorCategory.EMPTY_EVENTS: "Both",
        ErrorCategory.DOWNLOAD_WITH_SERVICES: "Both",
        ErrorCategory.DOWNLOAD_NO_VISIBILITY: "Both",
        ErrorCategory.SERVICE_NO_STEPS: "Both",
    }

    def _pct(v: float) -> str:
        return f"{v * 100:.0f}%"

    for cat in ErrorCategory:
        if cat == ErrorCategory.VALID:
            continue
        s = results[ValidationArm.SCHEMA].get(cat, 0.0)
        p = results[ValidationArm.POLICY].get(cat, 0.0)
        c = results[ValidationArm.COMBINED].get(cat, 0.0)
        layer = layer_map.get(cat, "?")
        lines.append(f"| {cat.value} | {layer} | {_pct(s)} | {_pct(p)} | {_pct(c)} |")

    # Summary row
    cats = [c for c in ErrorCategory if c != ErrorCategory.VALID]
    s_avg = sum(results[ValidationArm.SCHEMA].get(c, 0.0) for c in cats) / len(cats)
    p_avg = sum(results[ValidationArm.POLICY].get(c, 0.0) for c in cats) / len(cats)
    c_avg = sum(results[ValidationArm.COMBINED].get(c, 0.0) for c in cats) / len(cats)
    lines.append(f"| **Average detection** | — | **{_pct(s_avg)}** | **{_pct(p_avg)}** | **{_pct(c_avg)}** |")

    # False positive row
    s_fp = results[ValidationArm.SCHEMA].get(ErrorCategory.VALID, 0.0)
    p_fp = results[ValidationArm.POLICY].get(ErrorCategory.VALID, 0.0)
    c_fp = results[ValidationArm.COMBINED].get(ErrorCategory.VALID, 0.0)
    lines.append(f"| **False positive rate** | — | **{_pct(s_fp)}** | **{_pct(p_fp)}** | **{_pct(c_fp)}** |")

    return "\n".join(lines)
