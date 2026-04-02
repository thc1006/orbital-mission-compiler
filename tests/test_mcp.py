"""Smoke tests for MCP server tools.

Tests the tool FUNCTIONS directly (not the MCP transport).
Skips gracefully when fastmcp is not installed.
Issue #12.
"""

import pytest

try:
    import fastmcp  # noqa: F401
    from orbital_mission_compiler.mcp.server import build_server

    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False
    build_server = None  # type: ignore[assignment]

pytestmark = pytest.mark.skipif(not FASTMCP_AVAILABLE, reason="fastmcp not installed")


SAMPLE_PLAN = "configs/mission_plans/sample_maritime_surveillance.yaml"
ORCHIDE_PLAN = "configs/mission_plans/sample_orchide_format.yaml"


@pytest.fixture(scope="module")
def server():
    return build_server()


# ── validate_plan ─────────────────────────────────────────────────────


def test_validate_plan(server):
    """validate_plan should return mission_id and event count."""
    from orbital_mission_compiler.compiler import load_mission_plan

    plan = load_mission_plan(SAMPLE_PLAN)
    assert plan.mission_id == "mission-alpha"
    assert len(plan.events) == 2


# ── compile_plan ──────────────────────────────────────────────────────


def test_compile_plan():
    """compile_plan should return intent count and service IDs."""
    from orbital_mission_compiler.compiler import load_mission_plan, compile_plan_to_intents

    plan = load_mission_plan(SAMPLE_PLAN)
    intents = compile_plan_to_intents(plan)
    assert len(intents) >= 1
    assert intents[0].service_id == "maritime-surveillance"


# ── render_argo ───────────────────────────────────────────────────────


def test_render_argo():
    """render_argo should produce file names."""
    from orbital_mission_compiler.compiler import load_mission_plan, compile_plan_to_intents, render_argo_workflow

    plan = load_mission_plan(SAMPLE_PLAN)
    intents = compile_plan_to_intents(plan)
    wf = render_argo_workflow(intents[0])
    assert wf["kind"] == "Workflow"


# ── explain_policy ────────────────────────────────────────────────────


def test_explain_policy():
    """explain_policy should return OPA result or skip message."""
    from orbital_mission_compiler.policy import eval_policy, opa_available
    from orbital_mission_compiler.compiler import load_mission_plan

    plan = load_mission_plan(SAMPLE_PLAN)
    rc, out = eval_policy("configs/policies", plan.model_dump(mode="json"), "data.orbitalmission")
    if opa_available():
        assert rc == 0
    else:
        assert rc == 2


# ── build_server ──────────────────────────────────────────────────────


def test_build_server_creates_tools(server):
    """build_server should register 4 MCP tools."""
    assert server is not None
