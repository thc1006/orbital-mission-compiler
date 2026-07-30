from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

try:
    from fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[assignment,misc]

from orbital_mission_compiler import baseline_validator
from orbital_mission_compiler.compiler import (
    PolicyEngineUnavailableError,
    PolicyViolationError,
    analyze_timeline_conflicts,
    compile_plan_to_intents,
    enforce_policy_or_raise,
    load_mission_plan,
    typed_violations_from_decision,
    write_individual_workflows,
)
from orbital_mission_compiler.policy import eval_policy

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ALLOWED_PLANS = (_REPO_ROOT / "configs" / "mission_plans").resolve()
_ALLOWED_BUNDLES = (_REPO_ROOT / "configs" / "policies").resolve()


def _is_within(child: Path, parent: Path) -> bool:
    """Check if child path is within or equal to parent directory."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_plan_path(path: str) -> Path:
    """Validate plan path is a filename within configs/mission_plans/. CWE-22 prevention."""
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Path outside allowed directory: {path}")
    # Only accept bare filenames — reject paths with directory components
    if candidate != Path(candidate.name):
        raise ValueError(f"Path outside allowed directory: {path}")
    resolved = (_ALLOWED_PLANS / candidate.name).resolve()
    if not _is_within(resolved, _ALLOWED_PLANS):
        raise ValueError(f"Path outside allowed directory: {path}")
    if not resolved.exists():
        raise ValueError(f"Plan file not found: {path}")
    return resolved


def _validate_bundle_path(bundle: str) -> Path:
    """Validate bundle path is within configs/policies/. CWE-22 prevention."""
    candidate = Path(bundle)
    # Resolve relative paths against _REPO_ROOT (CWD-independent)
    if not candidate.is_absolute():
        resolved = (_REPO_ROOT / candidate).resolve()
    else:
        resolved = candidate.resolve()
    if not _is_within(resolved, _ALLOWED_BUNDLES):
        raise ValueError(f"Bundle path outside allowed directory: {bundle}")
    return resolved


def build_server() -> Any:
    if FastMCP is None:
        raise RuntimeError(
            "fastmcp is not installed. Install optional extras with: pip install -e '.[mcp]'"
        )

    server = FastMCP("orbital-mission-compiler")

    @server.tool
    def validate_plan(path: str) -> dict[str, Any]:
        """Report BOTH schema validity and policy admissibility for a plan.

        Non-blocking: it tells the caller whether the plan would pass the admission
        gate (``policy_allowed``) and lists any ``violations``, so an agent sees the
        full picture before calling ``compile_plan``/``render_argo`` (which fail
        closed on a denied plan by default).
        """
        safe_path = _validate_plan_path(path)
        plan = load_mission_plan(safe_path)
        # Typed, occurrence-level violations {rule, severity, provenance, path, message}
        # so an agent can triage without re-parsing prose.
        violations = baseline_validator.violations(plan.model_dump(mode="json"))
        return {
            "mission_id": plan.mission_id,
            "events": len(plan.events),
            "schema": "valid",
            "policy_allowed": not violations,
            "violations": violations,
            "status": "validated" if not violations else "policy_denied",
        }

    @server.tool
    def compile_plan(path: str, unsafe_skip_policy: bool = False) -> dict[str, Any]:
        """Compile a plan to workflow intents. Fail-closed: a policy-denied plan
        yields ``status: "denied"`` with its violations and no compilation, unless
        ``unsafe_skip_policy=True`` (dev only)."""
        safe_path = _validate_plan_path(path)
        plan = load_mission_plan(safe_path)
        if not unsafe_skip_policy:
            try:
                enforce_policy_or_raise(plan)
            except PolicyViolationError as exc:
                return {"status": "denied", "mission_id": plan.mission_id, "violations": exc.violations}
        intents = compile_plan_to_intents(plan)
        return {
            "status": "ok",
            "mission_id": plan.mission_id,
            "intent_count": len(intents),
            "services": [intent.service_id for intent in intents],
        }

    @server.tool
    def render_argo(path: str, unsafe_skip_policy: bool = False) -> dict[str, Any]:
        """Render Argo Workflow manifests. Fail-closed: no artifact is produced for
        a policy-denied plan (``status: "denied"``) unless ``unsafe_skip_policy=True``."""
        safe_path = _validate_plan_path(path)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                files = write_individual_workflows(
                    safe_path, tmpdir, enforce_policy=not unsafe_skip_policy
                )
                return {"status": "ok", "files": [f.name for f in files], "count": len(files)}
        except PolicyViolationError as exc:
            return {"status": "denied", "violations": exc.violations}

    @server.tool
    def explain_policy(
        path: str, bundle: str = "configs/policies", decision: str = "data.orbitalmission"
    ) -> dict[str, Any]:
        safe_path = _validate_plan_path(path)
        safe_bundle = _validate_bundle_path(bundle)
        plan = load_mission_plan(safe_path)
        rc, out = eval_policy(str(safe_bundle), plan.model_dump(mode="json"), decision)
        result: dict[str, Any] = {"exit_code": rc, "raw": out}
        # Surface the typed violations so an agent can reason over the rule id,
        # severity tier and provenance instead of parsing the raw OPA text.
        # `raw` stays for debugging and for a custom decision that carries neither.
        try:
            value = json.loads(out)["result"][0]["expressions"][0]["value"]
        except (ValueError, KeyError, IndexError, TypeError):
            return result
        try:
            typed = typed_violations_from_decision(value)
        except PolicyEngineUnavailableError as exc:
            # A decision this gate cannot trust is reported as undecidable rather
            # than as an empty violation list, which an agent would read as allowed.
            result["denied"] = None
            result["error"] = str(exc)
            return result
        result["violations"] = typed
        result["denied"] = bool(typed)
        return result

    @server.tool
    def diff_plans(path_a: str, path_b: str) -> dict[str, Any]:
        """Structural diff of two mission plans."""
        plan_a = load_mission_plan(_validate_plan_path(path_a))
        plan_b = load_mission_plan(_validate_plan_path(path_b))

        services_a = {
            svc.service_id for ev in plan_a.events for svc in ev.services
        }
        services_b = {
            svc.service_id for ev in plan_b.events for svc in ev.services
        }
        return {
            "mission_a": plan_a.mission_id,
            "mission_b": plan_b.mission_id,
            "events_a": len(plan_a.events),
            "events_b": len(plan_b.events),
            "added_services": sorted(services_b - services_a),
            "removed_services": sorted(services_a - services_b),
            "common_services": sorted(services_a & services_b),
        }

    @server.tool
    def check_timeline_conflicts(path: str) -> dict[str, Any]:
        """Detect overlapping acquisition windows in a mission plan."""
        plan = load_mission_plan(_validate_plan_path(path))
        return analyze_timeline_conflicts(plan)

    return server


def main() -> None:
    server = build_server()
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    server.run(transport=transport)


if __name__ == "__main__":
    main()
