"""Tests for the selectable policy engine (#1) and fail-closed enforcement.

The gate runs through ``evaluate_policy_decision`` with a chosen engine:
- ``opa``     — executes the versioned, auditable Rego bundle (authoritative);
                the default for the artifact-producing CLI commands.
- ``baseline`` — the proven-equivalent in-process mirror (offline/tests).

A selected engine that cannot render a decision (e.g. ``opa`` absent) must fail
CLOSED — raise ``PolicyEngineUnavailableError``, never silently downgrade or skip.
"""

import sys

import pytest

from orbital_mission_compiler import compiler
from orbital_mission_compiler.compiler import (
    PolicyEngineUnavailableError,
    evaluate_policy_decision,
    load_mission_plan,
)
from orbital_mission_compiler.policy import opa_available

VALID = "configs/mission_plans/sample_gpu_cpu_fallback.yaml"
DENIED = "configs/mission_plans/demo_gpu_no_fallback.yaml"


def _dump(path: str) -> dict:
    return load_mission_plan(path).model_dump(mode="json")


def _canon(vs: list[dict]) -> list:
    return sorted((v["rule"], v["severity"], v["provenance"], v["path"], v["message"]) for v in vs)


# ── engine equivalence (the whole point of the dual-engine claim) ────────


@pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")
@pytest.mark.parametrize("path", [VALID, DENIED])
def test_opa_and_baseline_engines_produce_identical_typed_violations(path):
    plan = _dump(path)
    opa = evaluate_policy_decision(plan, engine="opa")
    base = evaluate_policy_decision(plan, engine="baseline")
    assert _canon(opa) == _canon(base)


def test_baseline_engine_needs_no_opa():
    # The baseline engine must work regardless of opa availability.
    assert evaluate_policy_decision(_dump(VALID), engine="baseline") == []
    assert evaluate_policy_decision(_dump(DENIED), engine="baseline")  # non-empty


# ── fail-closed when the selected engine cannot decide ───────────────────


def test_opa_engine_fails_closed_when_opa_unavailable(monkeypatch):
    monkeypatch.setattr("orbital_mission_compiler.policy.opa_available", lambda: False)
    with pytest.raises(PolicyEngineUnavailableError):
        evaluate_policy_decision(_dump(VALID), engine="opa")


def test_unknown_engine_raises():
    with pytest.raises(ValueError, match="unknown policy engine"):
        evaluate_policy_decision(_dump(VALID), engine="bogus")


# ── CLI default engine is opa (authoritative), and it too fails closed ───


@pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")
def test_cli_default_engine_opa_denies(tmp_path, capsys, monkeypatch):
    from orbital_mission_compiler.cli import main

    out = tmp_path / "o.json"
    # No --policy-engine -> default opa -> runs the real .rego -> denied.
    monkeypatch.setattr(sys, "argv", ["prog", "compile", "--input", DENIED, "--output", str(out)])
    with pytest.raises(SystemExit) as se:
        main()
    assert se.value.code == 1
    assert "denied" in capsys.readouterr().err
    assert not out.exists()


def test_cli_opa_default_fails_closed_when_opa_absent(tmp_path, capsys, monkeypatch):
    from orbital_mission_compiler.cli import main

    # Default engine is opa; if opa is unavailable the CLI must fail closed with a
    # distinct exit code (2) and NO artifact -- never silently skip the gate.
    monkeypatch.setattr("orbital_mission_compiler.policy.opa_available", lambda: False)
    out = tmp_path / "o2.json"
    monkeypatch.setattr(sys, "argv", ["prog", "compile", "--input", VALID, "--output", str(out)])
    with pytest.raises(SystemExit) as se:
        main()
    assert se.value.code == 2
    assert "policy_engine_unavailable" in capsys.readouterr().err
    assert not out.exists()


def test_cli_baseline_engine_compiles_without_opa(tmp_path, monkeypatch):
    from orbital_mission_compiler.cli import main

    # Explicit baseline engine works even with opa absent.
    monkeypatch.setattr("orbital_mission_compiler.policy.opa_available", lambda: False)
    out = tmp_path / "o3.json"
    monkeypatch.setattr(
        sys, "argv",
        ["prog", "compile", "--input", VALID, "--output", str(out), "--policy-engine", "baseline"],
    )
    main()
    assert out.exists()


def test_enforce_error_carries_typed_violations():
    # #7: the typed {rule,severity,provenance,path,message} must survive the
    # enforcement boundary, not be flattened to strings.
    with pytest.raises(compiler.PolicyViolationError) as exc:
        compiler.enforce_policy_or_raise(load_mission_plan(DENIED), engine="baseline")
    v = exc.value.violations[0]
    assert set(v) == {"rule", "severity", "provenance", "path", "message"}
    assert exc.value.messages == [x["message"] for x in exc.value.violations]
