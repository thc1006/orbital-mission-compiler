#!/usr/bin/env python3
"""End-to-end MCP agent-workflow demo (paper Section IV).

Simulates an AI agent admitting a mission plan through the MCP tools: it
validates the plan, discovers a policy violation via ``explain_policy``, applies
a fix (a corrected plan), verifies the fix passes, then compiles and renders the
onboard artifacts. Every step invokes a REAL MCP tool through the server's
``call_tool`` API -- this is a utility demonstration of the tool surface, not a
mock.

Run:
    PATH="$PWD/.venv-verify/bin:$PATH" \\
    .venv-verify/bin/python scripts/mcp_agent_demo.py
Requires: fastmcp installed and the opa CLI on PATH.
"""

from __future__ import annotations

import asyncio
import json

from orbital_mission_compiler.mcp.server import build_server

BAD = "demo_gpu_no_fallback.yaml"
FIXED = "demo_gpu_fallback_fixed.yaml"


async def _call(server, name: str, args: dict) -> dict:
    result = await server.call_tool(name, args)
    return result.structured_content


def _policy_value(raw_result: dict) -> dict:
    return json.loads(raw_result["raw"])["result"][0]["expressions"][0]["value"]


async def main() -> None:
    server = build_server()
    print("=== MCP agent workflow: admit a mission plan ===\n")

    print(f"[1] validate_plan({BAD})  -- agent parses the candidate plan")
    print("   ", await _call(server, "validate_plan", {"path": BAD}), "\n")

    print(f"[2] explain_policy({BAD})  -- agent checks the guardrails")
    value = _policy_value(await _call(server, "explain_policy", {"path": BAD}))
    print("    allow:", value["allow"])
    for d in value.get("deny", []):
        print("    DENY:", d)
    print()

    print("[3] agent applies the fix suggested by the deny message:")
    print("    declares fallback_resource_class on the GPU step")
    print(f"    (-> {FIXED})\n")

    print(f"[4] explain_policy({FIXED})  -- agent re-checks the fix")
    value = _policy_value(await _call(server, "explain_policy", {"path": FIXED}))
    print("    allow:", value["allow"], "| deny:", value.get("deny", []), "\n")

    print(f"[5] compile_plan({FIXED})  -- agent compiles to WorkflowIntent IR")
    print("   ", await _call(server, "compile_plan", {"path": FIXED}), "\n")

    print(f"[6] render_argo({FIXED})  -- agent renders onboard artifacts")
    print("   ", await _call(server, "render_argo", {"path": FIXED}), "\n")

    print("=== plan admitted: diagnosed, fixed, verified, and compiled via MCP tools ===")


if __name__ == "__main__":
    asyncio.run(main())
