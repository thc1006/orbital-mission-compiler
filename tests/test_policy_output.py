"""Tests for policy.py output handling and public API.

H-1: stdout/stderr handling bug.
H-3: _sanitize_k8s_name should be public.
"""

from orbital_mission_compiler.policy import eval_policy, opa_available
from orbital_mission_compiler.compiler import sanitize_k8s_name  # H-3: should be public

import pytest

pytestmark = pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")


def test_policy_returns_stdout_when_present():
    """eval_policy should return stdout content, not stderr, when stdout is non-empty."""
    payload = {"mission_id": "test", "events": []}
    rc, out = eval_policy("configs/policies", payload, "data.orbitalmission")
    assert rc == 0
    assert "result" in out  # OPA JSON output should be in stdout


def test_sanitize_k8s_name_is_public():
    """sanitize_k8s_name should be importable as public API (no underscore)."""
    result = sanitize_k8s_name("My_Test-Name.123")
    assert result == "my-test-name-123"
