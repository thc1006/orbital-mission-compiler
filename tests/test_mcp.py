"""Smoke tests for MCP server tools.

Tests the MCP tool functions through the server's public async API.
Skips gracefully when fastmcp is not installed.
Issue #12.
"""

import asyncio
from pathlib import Path

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
    """render_argo MCP tool should return usable manifests, not stale names.

    The tool renders into a temporary directory that is removed before it
    returns, so handing back only file names would leave the caller holding
    paths that no longer exist.
    """
    import yaml as _yaml

    result = _call(server, "render_argo", {"path": SAMPLE_PLAN})
    assert result["count"] >= 1
    assert len(result["manifests"]) == result["count"]
    for manifest in result["manifests"]:
        doc = next(d for d in _yaml.safe_load_all(manifest["yaml"]) if d)
        assert doc["apiVersion"] == "argoproj.io/v1alpha1"
        assert doc["kind"] in {"Workflow", "ResourceClaimTemplate"} or doc["kind"] == "Workflow"


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


def test_compile_plan_unsafe_skip_compiles_denied(server, monkeypatch):
    monkeypatch.setenv("ORBITAL_MCP_ALLOW_POLICY_BYPASS", "1")
    result = _call(server, "compile_plan", {"path": DENIED_PLAN, "unsafe_skip_policy": True})
    assert result["status"] == "ok"
    assert result["intent_count"] >= 1


def test_render_argo_denied_blocks_by_default(server):
    """Fail-closed: no Argo artifact is produced for a denied plan by default."""
    result = _call(server, "render_argo", {"path": DENIED_PLAN})
    assert result["status"] == "denied"
    assert any("fallback_resource_class" in v["message"] for v in result["violations"])
    assert "files" not in result  # no artifact produced


def test_render_argo_unsafe_skip_renders_denied(server, monkeypatch):
    monkeypatch.setenv("ORBITAL_MCP_ALLOW_POLICY_BYPASS", "1")
    result = _call(server, "render_argo", {"path": DENIED_PLAN, "unsafe_skip_policy": True})
    assert result["status"] == "ok"
    assert result["count"] >= 1


def test_agent_cannot_bypass_the_gate_without_the_operator_switch(server):
    """The calling agent is untrusted, so the bypass must be an operator switch.

    A tool argument is reachable by anything that can shape a tool call,
    including injected text, so honouring it unconditionally would let a prompt
    turn off the admission gate.
    """
    for tool, key in (("render_argo", "violations"), ("compile_plan", "violations")):
        result = _call(server, tool, {"path": DENIED_PLAN, "unsafe_skip_policy": True})
        assert result["status"] == "denied", f"{tool} honoured the bypass unasked"
        assert result[key]


def test_every_tool_fails_closed_when_the_engine_cannot_decide(server, monkeypatch):
    """An engine that cannot run is not evidence that a plan is safe.

    Each artifact-producing tool reaches the evaluator by its own path, so each
    needs its own check: render_argo used to call the renderer directly, which
    both skipped the shared evaluator and surfaced a raw exception rather than a
    decision an agent can act on.
    """
    from orbital_mission_compiler.mcp import server as server_module

    monkeypatch.setattr(server_module, "MCP_POLICY_ENGINE", "bogus")
    for tool in ("validate_plan", "compile_plan", "render_argo"):
        result = _call(server, tool, {"path": SAMPLE_PLAN})
        assert result["status"] == "error", tool
        assert result["reason"] == "policy_engine_unavailable", tool
        # Nothing compiled, nothing rendered.
        assert "intent_count" not in result and "manifests" not in result, tool


# ── explain_policy tool ──────────────────────────────────────────────


def test_explain_policy_tool(server):
    """explain_policy MCP tool should return exit_code and raw output."""
    result = _call(server, "explain_policy", {"path": SAMPLE_PLAN})
    assert "exit_code" in result
    assert "raw" in result


def test_explain_policy_surfaces_typed_violations(server):
    """An agent must get the rule id, tier and provenance, not only raw text.

    The tool used to hand back the OPA output verbatim, so the safety
    categories the policy computes were unreachable from the agent side.
    """
    result = _call(server, "explain_policy", {"path": DENIED_PLAN})
    assert result.get("denied") is True
    assert result["violations"], "a denied plan must report at least one violation"
    for v in result["violations"]:
        assert set(v) == {"rule", "rule_id", "severity", "provenance", "path", "message"}
        assert v["severity"] in {"T1", "T2", "T3", "T4"}
        assert v["rule_id"].startswith("OMP-")
    # `raw` stays available for debugging.
    assert result["raw"]


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


# ── the gate judges the bytes it renders ─────────────────────────────


def test_render_argo_cannot_be_swapped_between_the_verdict_and_the_render(server, tmp_path, monkeypatch):
    """The plan is read once, so a file replaced after the verdict is not rendered.

    Reading the path for the policy decision and then handing the same path to
    the writer reads it twice. A plan that passes on the first read and is
    replaced before the second gets the approval earned by the reviewed content
    applied to content nobody reviewed.
    """
    import orbital_mission_compiler.compiler as compiler_mod

    allowed = Path("configs/mission_plans/demo_gpu_fallback_fixed.yaml").read_text(encoding="utf-8")
    denied = Path("configs/mission_plans/demo_gpu_no_fallback.yaml").read_text(encoding="utf-8")

    root = tmp_path / "plans"
    root.mkdir()
    target = root / "swap.yaml"
    target.write_text(allowed, encoding="utf-8")
    monkeypatch.setenv("ORBITAL_MCP_PLAN_ROOT", str(root))

    reads: list[int] = []
    real_load = compiler_mod.load_mission_plan

    def counting_load(path):
        reads.append(1)
        plan = real_load(path)
        # Swap in the plan the policy layer rejects, the way a writer that
        # re-read the path would pick it up.
        target.write_text(denied, encoding="utf-8")
        return plan

    monkeypatch.setattr(compiler_mod, "load_mission_plan", counting_load)
    monkeypatch.setattr("orbital_mission_compiler.mcp.server.load_mission_plan", counting_load)

    result = _call(server, "render_argo", {"path": "swap.yaml"})

    assert result["status"] == "ok", result
    assert len(reads) == 1, f"the plan file was read {len(reads)} times"
    # What was rendered is the approved content: it declares a fallback, so the
    # step carries the fallback env-var pair the denied plan cannot produce.
    rendered = "\n".join(m["yaml"] for m in result["manifests"])
    assert "ORBITAL_FALLBACK_RESOURCE_CLASS" in rendered, rendered[:400]
