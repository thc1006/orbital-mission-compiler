"""Tests for new MCP tools: diff_plans and check_timeline_conflicts."""

import asyncio

import pytest

try:
    from orbital_mission_compiler.mcp.server import build_server, FastMCP

    FASTMCP_AVAILABLE = FastMCP is not None
except ImportError:
    FASTMCP_AVAILABLE = False

pytestmark = pytest.mark.skipif(not FASTMCP_AVAILABLE, reason="fastmcp not installed")


@pytest.fixture(scope="module")
def server():
    return build_server()


def _call(server, name: str, args: dict):
    return asyncio.run(server.call_tool(name, args)).structured_content


# ── diff_plans ────────────────────────────────────────────────────────


def test_diff_plans_identical(server):
    """Diffing a plan against itself should show no changes."""
    result = _call(server, "diff_plans", {
        "path_a": "sample_maritime_surveillance.yaml",
        "path_b": "sample_maritime_surveillance.yaml",
    })
    assert result["added_services"] == []
    assert result["removed_services"] == []


def test_diff_plans_different(server):
    """Diffing two different plans should show differences."""
    result = _call(server, "diff_plans", {
        "path_a": "sample_maritime_surveillance.yaml",
        "path_b": "sample_gpu_cpu_fallback.yaml",
    })
    assert result["removed_services"] or result["added_services"]


# ── check_timeline_conflicts ──────────────────────────────────────────


def test_check_timeline_no_conflicts(server):
    """Plans with non-overlapping events should have zero conflicts."""
    result = _call(server, "check_timeline_conflicts", {
        "path": "sample_maritime_surveillance.yaml",
    })
    assert result["conflict_count"] == 0


def test_check_timeline_returns_structure(server):
    """Result should contain conflicts list, count, and skipped."""
    result = _call(server, "check_timeline_conflicts", {
        "path": "sample_orchide_format.yaml",
    })
    assert "conflicts" in result
    assert "conflict_count" in result
    assert "skipped_timestamps" in result


def test_check_timeline_detects_overlap(server):
    """Two acquisition events with overlapping windows should be detected."""
    import uuid

    import yaml

    plan = {
        "mission_id": "overlap-test",
        "events": [
            {
                "timestamp": "2029-01-01T00:00:00Z",
                "event_type": "acquisition",
                "instrument": "INST_1",
                "duration_seconds": 120.0,
            },
            {
                "timestamp": "2029-01-01T00:01:00Z",
                "event_type": "acquisition",
                "instrument": "INST_1",
                "duration_seconds": 120.0,
            },
        ],
    }
    from orbital_mission_compiler.mcp.server import _ALLOWED_PLANS

    filename = f"test_overlap_{uuid.uuid4().hex[:8]}.yaml"
    overlap_file = _ALLOWED_PLANS / filename
    overlap_file.write_text(yaml.safe_dump(plan), encoding="utf-8")
    try:
        result = _call(server, "check_timeline_conflicts", {
            "path": filename,
        })
        assert result["conflict_count"] == 1
        assert result["conflicts"][0]["overlap_seconds"] == 60.0
    finally:
        overlap_file.unlink(missing_ok=True)


def test_check_timeline_conflicts_uses_compiler_analysis(server, monkeypatch):
    """MCP tool should delegate timeline analysis to the compiler module helper."""
    calls = {"count": 0}

    def fake_analyze(_plan):
        calls["count"] += 1
        return {"conflicts": [], "conflict_count": 0, "skipped_timestamps": ["stubbed"]}

    monkeypatch.setattr("orbital_mission_compiler.mcp.server.analyze_timeline_conflicts", fake_analyze)
    result = _call(server, "check_timeline_conflicts", {
        "path": "sample_maritime_surveillance.yaml",
    })
    assert calls["count"] == 1
    assert result["skipped_timestamps"] == ["stubbed"]


# ── tool registration ─────────────────────────────────────────────────


def test_server_has_six_tools(server):
    """Server should now register 6 tools (4 original + 2 new)."""
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert "diff_plans" in names
    assert "check_timeline_conflicts" in names
    assert len(names) == 6
