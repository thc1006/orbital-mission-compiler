from __future__ import annotations

import os
import tempfile
from pathlib import Path

try:
    from fastmcp import FastMCP
except ImportError:
    FastMCP = None

from orbital_mission_compiler.compiler import (
    load_mission_plan,
    compile_plan_to_intents,
    write_individual_workflows,
)
from orbital_mission_compiler.policy import eval_policy

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ALLOWED_PLANS = _REPO_ROOT / "configs" / "mission_plans"
_ALLOWED_BUNDLES = _REPO_ROOT / "configs" / "policies"


def _validate_plan_path(path: str) -> Path:
    """Validate plan path is within configs/mission_plans/. CWE-22 prevention."""
    candidate = Path(path)
    # Absolute paths or any parent traversal → reject
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Path outside allowed directory: {path}")
    resolved = (_ALLOWED_PLANS / candidate.name).resolve()
    if not str(resolved).startswith(str(_ALLOWED_PLANS.resolve())):
        raise ValueError(f"Path outside allowed directory: {path}")
    if not resolved.exists():
        raise ValueError(f"Plan file not found: {path}")
    return resolved


def _validate_bundle_path(bundle: str) -> Path:
    """Validate bundle path is within configs/policies/. CWE-22 prevention."""
    resolved = Path(bundle).resolve()
    if not str(resolved).startswith(str(_ALLOWED_BUNDLES.resolve())):
        raise ValueError(f"Bundle path outside allowed directory: {bundle}")
    return resolved


def build_server():
    if FastMCP is None:
        raise RuntimeError(
            "fastmcp is not installed. Install optional extras with: pip install -e '.[mcp]'"
        )

    server = FastMCP("orbital-mission-compiler")

    @server.tool
    def validate_plan(path: str) -> dict:
        safe_path = _validate_plan_path(path)
        plan = load_mission_plan(safe_path)
        return {"mission_id": plan.mission_id, "events": len(plan.events), "status": "validated"}

    @server.tool
    def compile_plan(path: str) -> dict:
        safe_path = _validate_plan_path(path)
        plan = load_mission_plan(safe_path)
        intents = compile_plan_to_intents(plan)
        return {
            "mission_id": plan.mission_id,
            "intent_count": len(intents),
            "services": [intent.service_id for intent in intents],
        }

    @server.tool
    def render_argo(path: str) -> dict:
        safe_path = _validate_plan_path(path)
        with tempfile.TemporaryDirectory() as tmpdir:
            files = write_individual_workflows(safe_path, tmpdir)
            return {"files": [f.name for f in files], "count": len(files)}

    @server.tool
    def explain_policy(
        path: str, bundle: str = "configs/policies", decision: str = "data.orbitalmission"
    ) -> dict:
        safe_path = _validate_plan_path(path)
        _validate_bundle_path(bundle)
        plan = load_mission_plan(safe_path)
        rc, out = eval_policy(bundle, plan.model_dump(mode="json"), decision)
        return {"exit_code": rc, "raw": out}

    return server


def main():
    server = build_server()
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    server.run(transport=transport)


if __name__ == "__main__":
    main()
