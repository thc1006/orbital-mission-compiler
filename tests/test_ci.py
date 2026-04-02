"""Tests for CI/CD configuration existence and structure.

Verifies .github/workflows/ci.yml exists and contains expected jobs.
"""

from pathlib import Path
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
