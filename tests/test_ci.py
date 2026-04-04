"""Tests for CI/CD configuration existence and structure.

Verifies .github/workflows/ci.yml exists and contains expected jobs,
and that documentation stays in sync with source code.
"""

from pathlib import Path
import re
import yaml


def test_ci_workflow_exists():
    """GitHub Actions CI workflow must exist."""
    path = Path(".github/workflows/ci.yml")
    assert path.exists(), ".github/workflows/ci.yml must exist"


def test_ci_workflow_has_verify_job():
    """CI workflow must have a verify job."""
    path = Path(".github/workflows/ci.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = data.get("jobs", {})
    assert "verify" in jobs, "CI must have a 'verify' job"


def test_ci_workflow_triggers_on_pr():
    """CI must trigger on pull_request events."""
    path = Path(".github/workflows/ci.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # PyYAML parses quoted "on" as string key
    on_config = data.get("on", {})
    assert "pull_request" in on_config, "CI must trigger on pull_request"


def test_ci_workflow_has_mypy_step():
    """CI verify job must include a step that runs mypy."""
    path = Path(".github/workflows/ci.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = data.get("jobs", {}).get("verify", {}).get("steps", [])
    has_mypy_step = any(
        isinstance(step, dict)
        and isinstance(step.get("run"), str)
        and "mypy" in step["run"]
        for step in steps
    )
    assert has_mypy_step, "CI verify job must include a step that runs mypy"


def test_docs_mcp_tool_count_matches_source():
    """docs/04_architecture.md MCP tool count must match server.py @server.tool count."""
    server_path = Path("src/orbital_mission_compiler/mcp/server.py")
    actual_count = server_path.read_text(encoding="utf-8").count("@server.tool")

    doc_path = Path("docs/04_architecture.md")
    doc_text = doc_path.read_text(encoding="utf-8")
    match = re.search(r"(\d+)\s+MCP\s+tools", doc_text)
    assert match, "docs/04_architecture.md must mention MCP tool count"
    doc_count = int(match.group(1))
    assert doc_count == actual_count, (
        f"docs/04_architecture.md says {doc_count} MCP tools "
        f"but server.py has {actual_count} @server.tool decorators"
    )


def test_rego_rules_no_demo_language():
    """Rego policy rules should not contain environment-specific language."""
    rego_path = Path("configs/policies/mission_plan.rego")
    content = rego_path.read_text(encoding="utf-8")
    assert "local demo" not in content.lower(), (
        "Rego rules should not reference 'local demo' — "
        "policy messages must be environment-neutral"
    )
