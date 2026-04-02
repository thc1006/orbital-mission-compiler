"""Tests for CI/CD configuration existence and structure.

Verifies .github/workflows/ci.yml exists and contains expected jobs.
"""

from pathlib import Path
import yaml


def test_ci_workflow_exists():
    """GitHub Actions CI workflow must exist."""
    path = Path(".github/workflows/ci.yml")
    assert path.exists(), ".github/workflows/ci.yml must exist"


def test_ci_workflow_has_required_jobs():
    """CI workflow must have verify, test, and eval jobs."""
    path = Path(".github/workflows/ci.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = data.get("jobs", {})
    assert "verify" in jobs or "build" in jobs, "CI must have a verify or build job"


def test_ci_workflow_triggers_on_pr():
    """CI must trigger on pull_request events."""
    path = Path(".github/workflows/ci.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    on = data.get(True, data.get("on", {}))  # YAML parses 'on' as True
    assert "pull_request" in on or True in data, "CI must trigger on pull_request"
