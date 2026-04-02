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

SAMPLE_PLAN = "configs/mission_plans/sample_maritime_surveillance.yaml"


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


# ── explain_policy tool ──────────────────────────────────────────────


def test_explain_policy_tool(server):
    """explain_policy MCP tool should return exit_code and raw output."""
    result = _call(server, "explain_policy", {"path": SAMPLE_PLAN})
    assert "exit_code" in result
    assert "raw" in result


# ── build_server registers all 4 tools ───────────────────────────────


def test_build_server_registers_four_tools(server):
    """build_server should register exactly 4 MCP tools."""
    tools = asyncio.run(server.list_tools())
    tool_names = {t.name for t in tools}
    expected = {"validate_plan", "compile_plan", "render_argo", "explain_policy"}
    assert expected == tool_names
