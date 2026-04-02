"""Tests for policy.py output handling and public API.

H-1: stdout/stderr handling bug — test with mocked subprocess.
H-3: sanitize_k8s_name should be public.
"""

import subprocess
from unittest.mock import patch

import pytest

from orbital_mission_compiler.compiler import sanitize_k8s_name
from orbital_mission_compiler.policy import eval_policy, opa_available


# ── H-3: sanitize_k8s_name is public ─────────────────────────────────


def test_sanitize_k8s_name_is_public():
    """sanitize_k8s_name should be importable as public API (no underscore)."""
    result = sanitize_k8s_name("My_Test-Name.123")
    assert result == "my-test-name-123"


# ── H-1: stdout/stderr separation (mocked, no OPA required) ─────────


def test_policy_prefers_stdout_over_stderr():
    """When both stdout and stderr are present, eval_policy returns stdout."""
    fake = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout=b'{"result": "ok"}',
        stderr=b'WARNING: something',
    )
    with patch("orbital_mission_compiler.policy.subprocess.run", return_value=fake), \
         patch("orbital_mission_compiler.policy.opa_available", return_value=True):
        rc, out = eval_policy("configs/policies", {}, "data.orbitalmission")
    assert rc == 0
    assert out == '{"result": "ok"}'
    assert "WARNING" not in out


def test_policy_falls_back_to_stderr_when_stdout_empty():
    """When stdout is empty, eval_policy returns stderr."""
    fake = subprocess.CompletedProcess(
        args=[], returncode=1,
        stdout=b'',
        stderr=b'error: bundle not found',
    )
    with patch("orbital_mission_compiler.policy.subprocess.run", return_value=fake), \
         patch("orbital_mission_compiler.policy.opa_available", return_value=True):
        rc, out = eval_policy("configs/policies", {}, "data.orbitalmission")
    assert rc == 1
    assert "error: bundle not found" in out


# ── Integration test (requires real OPA) ─────────────────────────────


@pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")
def test_policy_returns_valid_json_with_real_opa():
    """Integration test: real OPA returns parseable JSON on stdout."""
    payload = {"mission_id": "test", "events": []}
    rc, out = eval_policy("configs/policies", payload, "data.orbitalmission")
    assert rc == 0
    assert "result" in out
