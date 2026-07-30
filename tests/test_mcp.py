"""Smoke tests for MCP server tools.

Tests the MCP tool functions through the server's public async API.
Skips gracefully when fastmcp is not installed.
Issue #12.
"""

import asyncio

import pytest

try:
    from orbital_mission_compiler.mcp.server import build_server, FastMCP

    FASTMCP_AVAILABLE = FastMCP is not None
except ImportError:
    FASTMCP_AVAILABLE = False
    build_server = None  # type: ignore[assignment]

pytestmark = pytest.mark.skipif(not FASTMCP_AVAILABLE, reason="fastmcp not installed")

SAMPLE_PLAN = "sample_maritime_surveillance.yaml"


@pytest.fixture(scope="module")
def server():
    return build_server()


def _call(server, name: str, args: dict):
    """Call an MCP tool through the server's async API."""
    result = asyncio.run(server.call_tool(name, args))
    return result.structured_content


# ── validate_plan tool ────────────────────────────────────────────────


def test_validate_plan_tool(server):
    """validate_plan MCP tool should return mission_id, events count, status."""
    result = _call(server, "validate_plan", {"path": SAMPLE_PLAN})
    assert result["mission_id"] == "mission-alpha"
    assert result["events"] == 2
    assert result["status"] == "validated"


# ── compile_plan tool ─────────────────────────────────────────────────


def test_compile_plan_tool(server):
    """compile_plan MCP tool should return intent_count and service list."""
    result = _call(server, "compile_plan", {"path": SAMPLE_PLAN})
    assert result["mission_id"] == "mission-alpha"
    assert result["intent_count"] >= 1
    assert "maritime-surveillance" in result["services"]


# ── render_argo tool ──────────────────────────────────────────────────


def test_render_argo_tool(server):
    """render_argo MCP tool should return file names and count."""
    result = _call(server, "render_argo", {"path": SAMPLE_PLAN})
    assert result["count"] >= 1
    assert len(result["files"]) >= 1


# ── fail-closed admission gate (deny path) ────────────────────────────

DENIED_PLAN = "demo_gpu_no_fallback.yaml"  # GPU step, no fallback -> Rule 4


def test_validate_plan_reports_policy_denial(server):
    """validate_plan must surface policy status, not just schema validity, so an
    agent sees a denied plan before it tries to compile."""
    result = _call(server, "validate_plan", {"path": DENIED_PLAN})
    assert result["schema"] == "valid"
    assert result["policy_allowed"] is False
    assert any("fallback_resource_class" in v["message"] for v in result["violations"])
    assert result["status"] == "policy_denied"


def test_compile_plan_denied_blocks_by_default(server):
    """Fail-closed: an agent calling compile_plan on a denied plan gets a denial
    and NO compilation -- it cannot skip the gate the way it could skip explain_policy."""
    result = _call(server, "compile_plan", {"path": DENIED_PLAN})
    assert result["status"] == "denied"
    assert any("fallback_resource_class" in v["message"] for v in result["violations"])
    assert "intent_count" not in result  # nothing was compiled


def test_compile_plan_unsafe_skip_compiles_denied(server):
    result = _call(server, "compile_plan", {"path": DENIED_PLAN, "unsafe_skip_policy": True})
    assert result["status"] == "ok"
    assert result["intent_count"] >= 1


def test_render_argo_denied_blocks_by_default(server):
    """Fail-closed: no Argo artifact is produced for a denied plan by default."""
    result = _call(server, "render_argo", {"path": DENIED_PLAN})
    assert result["status"] == "denied"
    assert any("fallback_resource_class" in v["message"] for v in result["violations"])
    assert "files" not in result  # no artifact produced


def test_render_argo_unsafe_skip_renders_denied(server):
    result = _call(server, "render_argo", {"path": DENIED_PLAN, "unsafe_skip_policy": True})
    assert result["status"] == "ok"
    assert result["count"] >= 1


# ── explain_policy tool ──────────────────────────────────────────────


def test_explain_policy_tool(server):
    """explain_policy MCP tool should return exit_code and raw output."""
    result = _call(server, "explain_policy", {"path": SAMPLE_PLAN})
    assert "exit_code" in result
    assert "raw" in result


# ── build_server registers all tools ──────────────────────────────────


def test_build_server_registers_all_tools(server):
    """build_server should register all MCP tools."""
    tools = asyncio.run(server.list_tools())
    tool_names = {t.name for t in tools}
    expected = {
        "validate_plan", "compile_plan", "render_argo", "explain_policy",
        "diff_plans", "check_timeline_conflicts",
    }
    assert expected == tool_names


# ── M9 end-to-end demo workflow (deny -> fix -> allow) ─────────────────


def test_mcp_demo_workflow(server):
    """M9 demo: the no-fallback plan is denied by policy via explain_policy and
    its fixed counterpart is allowed -- the deny->fix->verify loop the MCP tools
    enable for an agent (scripts/mcp_agent_demo.py)."""
    import json

    from orbital_mission_compiler.policy import opa_available

    if not opa_available():
        pytest.skip("OPA CLI not installed")

    bad = _call(server, "explain_policy", {"path": "demo_gpu_no_fallback.yaml"})
    bad_val = json.loads(bad["raw"])["result"][0]["expressions"][0]["value"]
    assert bad_val["allow"] is False
    assert any("fallback_resource_class" in d for d in bad_val["deny"])

    fixed = _call(server, "explain_policy", {"path": "demo_gpu_fallback_fixed.yaml"})
    fixed_val = json.loads(fixed["raw"])["result"][0]["expressions"][0]["value"]
    assert fixed_val["allow"] is True
    assert fixed_val["deny"] == []
