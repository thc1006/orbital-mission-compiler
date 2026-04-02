from __future__ import annotations

import os
import tempfile
from pathlib import Path

try:
    from fastmcp import FastMCP
except Exception:
    FastMCP = None

from orbital_mission_compiler.compiler import (
    load_mission_plan,
    compile_plan_to_intents,
    write_individual_workflows,
)
from orbital_mission_compiler.policy import eval_policy


def build_server():
    if FastMCP is None:
        raise RuntimeError(
            "fastmcp is not installed. Install optional extras with: pip install -e '.[mcp]'"
        )

    server = FastMCP("orbital-mission-compiler")

    @server.tool
    def validate_plan(path: str) -> dict:
        plan = load_mission_plan(path)
        return {"mission_id": plan.mission_id, "events": len(plan.events), "status": "validated"}

    @server.tool
    def compile_plan(path: str) -> dict:
        plan = load_mission_plan(path)
        intents = compile_plan_to_intents(plan)
        return {
            "mission_id": plan.mission_id,
            "intent_count": len(intents),
            "services": [intent.service_id for intent in intents],
        }

    @server.tool
    def render_argo(path: str) -> dict:
        with tempfile.TemporaryDirectory() as tmpdir:
            files = write_individual_workflows(path, tmpdir)
            return {"files": [Path(f).name for f in files], "count": len(files)}

    @server.tool
    def explain_policy(
        path: str, bundle: str = "configs/policies", decision: str = "data.orbitalmission"
    ) -> dict:
        plan = load_mission_plan(path)
        rc, out = eval_policy(bundle, plan.model_dump(mode="json"), decision)
        return {"exit_code": rc, "raw": out}

    return server


def main():
    server = build_server()
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    server.run(transport=transport)


if __name__ == "__main__":
    main()
