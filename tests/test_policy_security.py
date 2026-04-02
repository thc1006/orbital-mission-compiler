"""Security tests for policy.py.

S-H2: OPA subprocess must have timeout.
S-H3: OPA stderr must not leak to caller.
"""

import subprocess
from unittest.mock import patch

from orbital_mission_compiler.policy import eval_policy, OPA_TIMEOUT_SECONDS


def test_opa_timeout_is_set():
    """eval_policy must pass timeout=OPA_TIMEOUT_SECONDS to subprocess.run (CWE-400)."""
    fake = subprocess.CompletedProcess(args=[], returncode=0, stdout=b'{}', stderr=b'')
    with patch("orbital_mission_compiler.policy.subprocess.run", return_value=fake) as mock_run, \
         patch("orbital_mission_compiler.policy.opa_available", return_value=True):
        eval_policy("configs/policies", {"mission_id": "t", "events": []}, "data.orbitalmission")

    mock_run.assert_called_once()
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["timeout"] == OPA_TIMEOUT_SECONDS


def test_opa_timeout_returns_error_on_expire():
    """When OPA times out, eval_policy returns rc=1 with timeout message."""
    with patch("orbital_mission_compiler.policy.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="opa", timeout=OPA_TIMEOUT_SECONDS)), \
         patch("orbital_mission_compiler.policy.opa_available", return_value=True):
        rc, out = eval_policy("configs/policies", {}, "data.orbitalmission")

    assert rc == 1
    assert "timed out" in out.lower()
    assert str(OPA_TIMEOUT_SECONDS) in out


def test_stderr_not_leaked_when_stdout_present():
    """When stdout has content, stderr must not appear in output (CWE-209)."""
    fake = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout=b'{"result": []}',
        stderr=b'WARNING: internal path /opt/opa/bundle loaded',
    )
    with patch("orbital_mission_compiler.policy.subprocess.run", return_value=fake), \
         patch("orbital_mission_compiler.policy.opa_available", return_value=True):
        _, out = eval_policy("configs/policies", {}, "data.orbitalmission")

    assert "/opt/opa" not in out, "Internal paths from stderr must not leak"
