"""Security tests for policy.py.

S-H2: OPA subprocess must have timeout.
S-H3: OPA stderr must not leak to caller.
"""

import subprocess
from unittest.mock import patch

from orbital_mission_compiler.policy import eval_policy


def test_opa_timeout_is_set():
    """eval_policy must pass timeout to subprocess.run (CWE-400)."""
    calls = []
    original_run = subprocess.run

    def spy_run(*args, **kwargs):
        calls.append(kwargs)
        return original_run(*args, **kwargs)

    with patch("orbital_mission_compiler.policy.subprocess.run", side_effect=spy_run), \
         patch("orbital_mission_compiler.policy.opa_available", return_value=True):
        eval_policy("configs/policies", {"mission_id": "t", "events": []}, "data.orbitalmission")

    assert any("timeout" in c for c in calls), "subprocess.run must be called with timeout"


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
