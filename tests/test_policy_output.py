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
    import json

    payload = {"mission_id": "test", "events": []}
    rc, out = eval_policy("configs/policies", payload, "data.orbitalmission")
    assert rc == 0
    parsed = json.loads(out)
    assert "result" in parsed


# ── `policy` CLI subcommand is a real admission gate ─────────────────
# OPA's own exit code is 0 even for a denied plan; the command must gate on the
# DECISION. These fail if cmd_policy regresses to exiting on the subprocess rc.

VALID_PLAN = "configs/mission_plans/sample_gpu_cpu_fallback.yaml"
DENIED_PLAN = "configs/mission_plans/demo_gpu_no_fallback.yaml"  # Rule 4


@pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")
def test_cmd_policy_exits_nonzero_on_denied_plan(monkeypatch):
    import sys

    from orbital_mission_compiler.cli import main

    monkeypatch.setattr(sys, "argv", ["prog", "policy", "--input", DENIED_PLAN])
    with pytest.raises(SystemExit) as se:
        main()
    assert se.value.code == 1


@pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")
def test_cmd_policy_denial_reports_typed_violations(monkeypatch, capsys):
    """The denial payload must carry the categories the policy already computed.

    It previously emitted the plain-string `deny` projection under a
    `violations` key, which left CI with nothing to act on but the prose.
    """
    import json as _json
    import sys

    from orbital_mission_compiler.cli import main

    monkeypatch.setattr(sys, "argv", ["prog", "policy", "--input", DENIED_PLAN])
    with pytest.raises(SystemExit) as se:
        main()
    assert se.value.code == 1

    payload = _json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert payload["status"] == "denied"
    assert payload["violations"], "a denied plan must report at least one violation"
    for v in payload["violations"]:
        assert set(v) == {"rule", "rule_id", "severity", "provenance", "path", "message"}
        assert v["severity"] in {"T1", "T2", "T3", "T4"}
        assert v["provenance"] in {"A", "D"}
        assert v["rule_id"].startswith("OMP-")


@pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")
def test_cmd_policy_exits_zero_on_valid_plan(monkeypatch):
    import sys

    from orbital_mission_compiler.cli import main

    monkeypatch.setattr(sys, "argv", ["prog", "policy", "--input", VALID_PLAN])
    with pytest.raises(SystemExit) as se:
        main()
    assert se.value.code == 0


@pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")
def test_opa_smoke_script_gates_on_decision():
    """scripts/opa_smoke.sh must exit non-zero on a denied plan (its whole point:
    let the policy RESULT, not just 'did OPA run', control the exit code)."""
    import os
    import shutil
    import subprocess

    opa_bin = shutil.which("opa")
    assert opa_bin
    env = {**os.environ, "PATH": os.path.dirname(opa_bin) + os.pathsep + os.environ["PATH"]}
    ok = subprocess.run(["bash", "scripts/opa_smoke.sh", VALID_PLAN], env=env, capture_output=True)
    assert ok.returncode == 0, ok.stderr.decode()
    denied = subprocess.run(["bash", "scripts/opa_smoke.sh", DENIED_PLAN], env=env, capture_output=True)
    assert denied.returncode != 0, "opa_smoke did not gate on a denied plan"
