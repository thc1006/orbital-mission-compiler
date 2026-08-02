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
import shutil
import subprocess
from pathlib import Path

from orbital_mission_compiler.mcp.server import build_server
from orbital_mission_compiler.provenance import emit

BAD = "demo_gpu_no_fallback.yaml"
FIXED = "demo_gpu_fallback_fixed.yaml"

REPO = Path(__file__).resolve().parent.parent
# The two plans and the Rego pack the deny message comes from. The transcript in
# docs/experiments/2026-07-07-mcp-agent-demo.md is the paper's Section IV evidence,
# and its whole content is a policy decision about these files -- so a run against
# an edited plan or an edited policy is a different demonstration, and nothing in
# the output would have said so.
INPUTS = (
    REPO / "configs" / "mission_plans" / BAD,
    REPO / "configs" / "mission_plans" / FIXED,
    *sorted((REPO / "configs" / "policies").glob("*.rego")),
)


def _opa_version() -> str:
    """The OPA build behind steps 2 and 4, which are the substance of the demo."""
    binary = shutil.which("opa")
    if binary is None:
        return "not on PATH"
    try:
        proc = subprocess.run(
            [binary, "version"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unknown ({exc})"
    if proc.returncode != 0:
        return f"unknown (opa version exited {proc.returncode})"
    for line in proc.stdout.splitlines():
        if line.lower().startswith("version:"):
            return f"{line.split(':', 1)[1].strip()} ({binary})"
    return f"unknown (unrecognised output) ({binary})"


async def _call(server, name: str, args: dict) -> dict:
    result = await server.call_tool(name, args)
    return result.structured_content


def _policy_value(raw_result: dict) -> dict:
    return json.loads(raw_result["raw"])["result"][0]["expressions"][0]["value"]


async def main() -> None:
    emit(
        Path(__file__),
        repo=REPO,
        inputs=INPUTS,
        environment=(("opa", _opa_version()),),
        # A transcript of tool calls, not a measurement: the CPU it ran on has no
        # bearing on which plan the policy denies.
        include_host=False,
    )
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
