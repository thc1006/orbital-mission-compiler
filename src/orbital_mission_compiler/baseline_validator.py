"""Hand-written in-process Python baseline for the OPA/Rego policy.

This module re-implements the ten deny rules of
``configs/policies/mission_plan.rego`` in pure Python. It is one of two
interchangeable policy engines (see ``compiler.evaluate_policy_decision``): the
authoritative engine executes the versioned, independently-auditable Rego bundle
via ``opa``; this in-process baseline is a **proven-equivalent** fast/offline
engine. Section V-B quantifies the OPA-subprocess vs in-process cost.

Equivalence contract (asserted in ``tests/test_structured_violations.py``):
- the two engines make the SAME accept/reject decision on ALL inputs, including
  the raw-JSON bypass path (malformed / absent / null / wrong-typed fields);
- and produce IDENTICAL typed violations on inputs whose string identifiers
  (``name`` / ``service_id`` / ``landscape_type``) are free of control/quote
  characters -- which every schema-valid plan is. Each rule is evaluated
  INDEPENDENTLY (a malformed ``steps`` does not suppress the priority or
  landscape check), mirroring the Rego set semantics.

Each violation is occurrence-level: it carries a JSON-Pointer ``path`` to the
exact offending node, so two structurally-identical offenders are distinct.
"""

from __future__ import annotations

import json
from typing import Any

VALID_LANDSCAPE_TYPES = frozenset({"ocean", "land"})
ACCELERATOR_CLASSES = frozenset({"gpu", "fpga"})
# The only driver-backed non-accelerator fallback target (dra-driver-cpu backs
# `dra.cpu`; there is no FPGA DRA driver), so an accelerator step's fallback must
# resolve to CPU to be usable (Rule 4).
FALLBACK_CLASS = "cpu"

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
_STRUCTURAL_META = ("T1", "A")

# Stable identifier for consumers that key on the rule rather than reading the
# message: `OMP-004` for numbered rules, and one shared id for the structural
# fail-closed guard, which is not a numbered rule from the paper's table.
STRUCTURAL_RULE_ID = "OMP-STRUCTURAL"


def rule_id(rule: int | None) -> str:
    """Return the stable string id for a rule number (``None`` = structural guard)."""
    return STRUCTURAL_RULE_ID if rule is None else f"OMP-{rule:03d}"


def _viol(rule: int | None, message: str, path: str) -> dict[str, Any]:
    severity, provenance = _RULE_META[rule] if rule is not None else _STRUCTURAL_META
    return {
        "rule": rule,
        "rule_id": rule_id(rule),
        "severity": severity,
        "provenance": provenance,
        "path": path,
        "message": message,
    }


def _q(value: object) -> str:
    """Quote an interpolated identifier to match the Rego policy's ``sprintf %q``
    (Go ``strconv.Quote``) on the realistic character set: surrounding quotes plus
    ``\\`` ``\"`` ``\\t`` ``\\n`` ``\\r`` escaping, with printable Unicode left
    as-is. Schema-valid identifiers contain none of these, so this only shapes
    raw-JSON-bypass messages; both engines deny such input regardless."""
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    return json.dumps(value, ensure_ascii=False)


def _as_list(value: Any) -> tuple[list[Any], bool]:
    """Normalize a services/steps field. Returns (list, malformed).

    Absent or JSON ``null`` -> ([], False): treated as empty (the emptiness rule
    may fire). A present non-list scalar -> ([], True): structurally malformed, so
    the caller emits the structural guard and skips the container-dependent rule,
    but still evaluates rules that do not depend on the container. A list ->
    (list, False). Mirrors the Rego policy's handling exactly.
    """
    if value is None:
        return [], False
    if isinstance(value, list):
        return value, False
    return [], True


def violations(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return structured, occurrence-level policy violations for a plan dict.

    Collects ALL violations (no short-circuit that would hide an independent
    rule), so the accept/reject decision and the reported set match the Rego
    policy on every input.
    """
    out: list[dict[str, Any]] = []

    # Rule 1: mission_id must not be null, missing, or a blank string.
    mid = plan.get("mission_id")
    if mid is None or (isinstance(mid, str) and mid.strip() == ""):
        out.append(_viol(1, "mission_id must not be empty", "/mission_id"))

    # Rule 2 + events structural guard.
    events = plan.get("events")
    if events is None:
        return out + [_viol(2, "mission plan must contain at least one event", "/events")]
    if not isinstance(events, list):
        return out + [_viol(None, "events must be a list", "/events")]  # fail closed
    if len(events) == 0:
        out.append(_viol(2, "mission plan must contain at least one event", "/events"))

    for i, event in enumerate(events):
        ep = f"/events/{i}"
        if not isinstance(event, dict):
            out.append(_viol(None, f"event {i} must be an object", ep))
            continue
        etype = event.get("event_type")
        services, services_malformed = _as_list(event.get("services"))
        if services_malformed:
            out.append(_viol(None, f"event {i} services must be a list", f"{ep}/services"))

        # Rule 3: an acquisition event must declare >=1 service (services-dependent).
        if etype == "acquisition" and not services_malformed and len(services) == 0:
            out.append(
                _viol(3, f"acquisition event {i} must declare at least one service", f"{ep}/services")
            )
        # Rule 7: a download event must not carry services (services-dependent).
        if etype == "download" and not services_malformed and len(services) > 0:
            out.append(
                _viol(7, f"download event {i} must not declare services (transmission only)", ep)
            )
        # Rule 8: a download event requires ground visibility (INDEPENDENT of
        # services; compare against boolean True, not Python truthiness).
        if etype == "download" and event.get("ground_visibility") is not True:
            out.append(
                _viol(
                    8,
                    f"download event {i} requires ground_visibility "
                    "(station must be visible for transmission)",
                    ep,
                )
            )

        for j, svc in enumerate(services):
            sp = f"{ep}/services/{j}"
            if not isinstance(svc, dict):
                out.append(_viol(None, "service must be an object", sp))
                continue
            sid = svc.get("service_id", "")
            steps, steps_malformed = _as_list(svc.get("steps"))
            if steps_malformed:
                out.append(_viol(None, "service steps must be a list", f"{sp}/steps"))

            # Rule 5: priority must not be zero (INDEPENDENT of steps). Guard
            # against bool: Python `False == 0` is True but Rego `== 0` is not.
            prio = svc.get("priority")
            if prio == 0 and not isinstance(prio, bool):
                out.append(
                    _viol(5, f"service {_q(sid)} has zero priority, which is likely a misconfiguration", sp)
                )
            # Rule 9: a service must have >=1 step (steps-dependent).
            if not steps_malformed and len(steps) == 0:
                out.append(_viol(9, f"service {_q(sid)} has no steps and cannot produce a workflow", sp))
            # Rule 10: landscape_type, when present, must be recognized (INDEPENDENT
            # of steps). Optional: a missing/null value is permitted.
            lt = svc.get("landscape_type")
            if isinstance(lt, str) and lt not in VALID_LANDSCAPE_TYPES:
                out.append(
                    _viol(10, f"service {_q(sid)} has unrecognized landscape_type {_q(lt)} (expected: ocean, land)", sp)
                )
            elif lt is not None and not isinstance(lt, str):
                out.append(
                    _viol(
                        10,
                        f"service {_q(sid)} has a non-string landscape_type "
                        "(expected a string: ocean or land)",
                        sp,
                    )
                )

            for k, step in enumerate(steps):
                stp = f"{sp}/steps/{k}"
                if not isinstance(step, dict):
                    out.append(_viol(None, "step must be an object", stp))
                    continue
                rc = step.get("resource_class")
                name = step.get("name", "")
                # Rule 4: an accelerator-bound step (GPU/FPGA) must declare a
                # *usable* fallback -- present AND resolving to CPU.
                if rc in ACCELERATOR_CLASSES:
                    fb = step.get("fallback_resource_class")
                    if fb is None:
                        out.append(
                            _viol(
                                4,
                                f"accelerator step {_q(name)} (resource_class {_q(rc)}) "
                                "must declare fallback_resource_class",
                                stp,
                            )
                        )
                    elif fb != FALLBACK_CLASS:
                        out.append(
                            _viol(
                                4,
                                f"accelerator step {_q(name)} (resource_class {_q(rc)}) declares "
                                f'fallback_resource_class {fb}, but the only usable fallback is "cpu"',
                                stp,
                            )
                        )
                # Rule 6: needs_acceleration on a CPU step is contradictory.
                if rc == "cpu" and step.get("needs_acceleration") is True:
                    out.append(
                        _viol(6, f"step {_q(name)} claims needs_acceleration but uses cpu resource class", stp)
                    )

    return out


def evaluate(plan: dict[str, Any]) -> list[str]:
    """Return the deny messages (message projection of ``violations``)."""
    return [v["message"] for v in violations(plan)]


def is_allowed(plan: dict[str, Any]) -> bool:
    """Return True iff the plan violates no deny rule (mirrors OPA ``allow``)."""
    return len(violations(plan)) == 0
