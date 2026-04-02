from __future__ import annotations

import os

try:
    from fastmcp import FastMCP
except Exception:
    FastMCP = None

from orbital_mission_compiler.compiler import load_mission_plan, compile_plan_to_intents


def build_server():
    if FastMCP is None:
        raise RuntimeError(
            "fastmcp is not installed. Install optional extras with: pip install -e '.[mcp]'"
        )

    server = FastMCP("orbital-mission-compiler")

    @server.tool
    def validate_plan(path: str) -> dict:
        plan = load_mission_plan(path)
        return {
            "mission_id": plan.mission_id,
            "events": len(plan.events),
            "status": "validated",
        }

    @server.tool
    def compile_plan(path: str) -> dict:
        plan = load_mission_plan(path)
        intents = compile_plan_to_intents(plan)
        return {
            "mission_id": plan.mission_id,
            "intent_count": len(intents),
            "services": [intent.service_id for intent in intents],
        }

    return server


def main():
    server = build_server()
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    server.run(transport=transport)


if __name__ == "__main__":
    main()
