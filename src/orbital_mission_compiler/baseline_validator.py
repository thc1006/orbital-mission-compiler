"""Hand-written in-process Python baseline for the OPA/Rego policy.

This module re-implements the ten deny rules of
``configs/policies/mission_plan.rego`` in pure Python so the paper can quantify
the runtime cost of the OPA subprocess model against an equivalent in-process
validator (Section V-B). It is a *performance baseline and equivalence oracle*,
NOT a production replacement: the OPA path is retained precisely for the
governance properties -- version control, independent review, and audit by a
party who does not execute the compiler -- that an in-process Python validator
cannot provide (Section II-B).

Rule-for-rule fidelity with the Rego source, including its null-handling
(``is_string()`` / ``!= null`` guards that permit a missing or JSON-null
Optional field), is asserted over the ablation corpus in
``tests/test_baseline_validator.py``.

``violations()`` additionally attaches the machine-readable severity tier
(T1-T4) and provenance (D = ORCHIDE-derived, A = author-imposed) from the paper's
loss-event taxonomy (Table III), so a consumer gets structured decisions rather
than plain deny strings. ``evaluate()`` is the message projection of
``violations()`` -- so the deny set stays byte-identical to the Rego ``deny``.
"""

from __future__ import annotations

from typing import Any

VALID_LANDSCAPE_TYPES = frozenset({"ocean", "land"})
ACCELERATOR_CLASSES = frozenset({"gpu", "fpga"})

# Per-rule severity tier (T1-T4) and provenance (A/D), authoritative from the
# paper's Table III (Pre-Uplink Loss-Event Severity Tiers) and its provenance
# footnote: T1{1,2}, T2{4,6}, T3{7,8}, T4{3,5,9,10}.
_RULE_META: dict[int, tuple[str, str]] = {
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
# Structural fail-closed guards for malformed input (non-list events, non-object
# step, ...). These are normally caught by Pydantic at Stage 1; when reached on
# the raw-JSON bypass path they are plan-malformed detections, so they take the
# T1 tier and the author-imposed provenance.
_STRUCTURAL_META = ("T1", "A")


def _viol(rule: int | None, message: str) -> dict[str, Any]:
    severity, provenance = _RULE_META[rule] if rule is not None else _STRUCTURAL_META
    return {"rule": rule, "severity": severity, "provenance": provenance, "message": message}


def violations(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return structured policy violations for a mission-plan dict.

    Each entry is ``{"rule": int|None, "severity": "T1".."T4", "provenance":
    "A"|"D", "message": str}``. Collects ALL violations (no short-circuit),
    mirroring OPA's ``deny`` set, so the accept/reject decision and the work
    performed match the Rego policy.
    """
    out: list[dict[str, Any]] = []

    # Rule 1: mission_id must not be null, missing, or a blank string.
    mid = plan.get("mission_id")
    if mid is None or (isinstance(mid, str) and mid.strip() == ""):
        out.append(_viol(1, "mission_id must not be empty"))

    # Rule 2: the plan must contain at least one event.
    events = plan.get("events") or []
    if not isinstance(events, list):
        return out + [_viol(None, "events must be a list")]  # fail closed on malformed input
    if len(events) == 0:
        out.append(_viol(2, "mission plan must contain at least one event"))

    for i, event in enumerate(events):
        if not isinstance(event, dict):
            out.append(_viol(None, f"event {i} must be an object"))
            continue
        etype = event.get("event_type")
        services = event.get("services") or []
        if not isinstance(services, list):
            out.append(_viol(None, f"event {i} services must be a list"))
            continue

        # Rule 3: an acquisition event must declare at least one service.
        if etype == "acquisition" and len(services) == 0:
            out.append(_viol(3, f"acquisition event {i} must declare at least one service"))

        # Rule 7: a download event must not carry services (transmission only).
        if etype == "download" and len(services) > 0:
            out.append(_viol(7, f"download event {i} must not declare services (transmission only)"))

        # Rule 8: a download event requires ground visibility. Matches the Rego
        # `not event.ground_visibility` on all schema-reachable inputs, where
        # ground_visibility is a non-optional bool (never JSON null).
        if etype == "download" and not event.get("ground_visibility"):
            out.append(
                _viol(
                    8,
                    f"download event {i} requires ground_visibility "
                    "(station must be visible for transmission)",
                )
            )

        for svc in services:
            if not isinstance(svc, dict):
                out.append(_viol(None, "service must be an object"))
                continue
            sid = svc.get("service_id")
            steps = svc.get("steps") or []
            if not isinstance(steps, list):
                out.append(_viol(None, f'service "{sid}" steps must be a list'))
                continue

            # Rule 5: service priority must not be zero.
            if svc.get("priority") == 0:
                out.append(
                    _viol(5, f'service "{sid}" has zero priority, which is likely a misconfiguration')
                )

            # Rule 9: a service must have at least one step.
            if len(steps) == 0:
                out.append(_viol(9, f'service "{sid}" has no steps and cannot produce a workflow'))

            # Rule 10: landscape_type, when present, must be recognized. The
            # field is optional -- a missing or JSON-null value is permitted --
            # so only a present value is checked (mirrors is_string()/!=null).
            lt = svc.get("landscape_type")
            if isinstance(lt, str) and lt not in VALID_LANDSCAPE_TYPES:
                out.append(
                    _viol(10, f'service "{sid}" has unrecognized landscape_type "{lt}" (expected: ocean, land)')
                )
            elif lt is not None and not isinstance(lt, str):
                out.append(
                    _viol(
                        10,
                        f'service "{sid}" has a non-string landscape_type '
                        "(expected a string: ocean or land)",
                    )
                )

            for step in steps:
                if not isinstance(step, dict):
                    out.append(_viol(None, "step must be an object"))
                    continue
                rc = step.get("resource_class")
                # Rule 4: any accelerator-bound step (GPU or FPGA) must declare
                # a fallback, independent of the optional needs_acceleration flag.
                if rc in ACCELERATOR_CLASSES and step.get("fallback_resource_class") is None:
                    name = step.get("name")
                    out.append(
                        _viol(
                            4,
                            f'accelerator step "{name}" (resource_class "{rc}") '
                            "must declare fallback_resource_class",
                        )
                    )
                # Rule 6: needs_acceleration on a CPU step is contradictory.
                if rc == "cpu" and step.get("needs_acceleration") is True:
                    name = step.get("name")
                    out.append(
                        _viol(6, f'step "{name}" claims needs_acceleration but uses cpu resource class')
                    )

    return out


def evaluate(plan: dict[str, Any]) -> list[str]:
    """Return the deny messages for a mission-plan dict (the message projection
    of ``violations()`` -- byte-identical to the Rego ``deny`` set)."""
    return [v["message"] for v in violations(plan)]


def is_allowed(plan: dict[str, Any]) -> bool:
    """Return True iff the plan violates no deny rule (mirrors OPA ``allow``)."""
    return len(violations(plan)) == 0
