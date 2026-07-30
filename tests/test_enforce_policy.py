"""Effective tests for opt-in policy enforcement in the pipeline (P0-1).

Enforcement is fail-closed: with enforce_policy=True a plan the policy layer would
deny produces NO artifact and a non-zero CLI exit. It is opt-in, so the default path
still renders (the four stages stay independently runnable, Section II-B).

Every test here is designed to FAIL if the implementation regresses:
- the block test asserts the surfaced violations EQUAL the policy layer's output
  (a stub that raised an empty error would fail),
- the default test asserts a denied plan still renders (an always-on regression fails),
- the compile_file test asserts NO output file is written (a write-then-raise fails).
"""

import sys

import pytest

from orbital_mission_compiler import baseline_validator
from orbital_mission_compiler.compiler import (
    PolicyViolationError,
    compile_file,
    enforce_policy_or_raise,
    load_mission_plan,
    render_workflows_for_file,
)

VALID = "configs/mission_plans/sample_gpu_cpu_fallback.yaml"
DENIED = "configs/mission_plans/demo_gpu_no_fallback.yaml"  # GPU step, no fallback -> Rule 4


def _policy_violations(path: str) -> list[str]:
    return baseline_validator.evaluate(load_mission_plan(path).model_dump(mode="json"))


def test_fixture_premise_schema_valid_but_policy_invalid():
    """Guards the whole file: DENIED must load (schema-valid) yet violate a rule,
    else the enforcement tests below would prove nothing."""
    load_mission_plan(DENIED)  # no exception -> schema-valid
    violations = _policy_violations(DENIED)
    assert violations, "fixture must actually violate a policy rule"
    assert any("fallback_resource_class" in v for v in violations)
    assert _policy_violations(VALID) == []  # and the valid plan must be clean


def test_enforce_blocks_and_surfaces_the_real_violation():
    with pytest.raises(PolicyViolationError) as exc:
        render_workflows_for_file(DENIED, enforce_policy=True)
    # Must surface the SAME decision the policy layer produces (not a generic
    # error): proves enforcement actually ran the policy rather than a stub.
    assert exc.value.violations == _policy_violations(DENIED)
    assert "detect-ships" in str(exc.value)


def test_default_still_renders_a_denied_plan():
    # Opt-in guarantee: without enforcement the denied plan still renders. An
    # always-enforce regression would fail here.
    workflows = render_workflows_for_file(DENIED)
    assert len(workflows) >= 1


def test_enforce_allows_valid_plan_with_identical_output():
    # Enforcement must not over-block a valid plan and must not alter the output.
    assert render_workflows_for_file(VALID, enforce_policy=True) == render_workflows_for_file(VALID)


def test_compile_file_enforce_writes_no_artifact(tmp_path):
    # Fail-closed property: a denied plan produces NO output file. A write-then-raise
    # ordering bug would leave the file behind and fail this test.
    out = tmp_path / "out.json"
    with pytest.raises(PolicyViolationError):
        compile_file(DENIED, out, enforce_policy=True)
    assert not out.exists()


def test_compile_file_enforce_valid_writes_artifact(tmp_path):
    out = tmp_path / "out.json"
    compile_file(VALID, out, enforce_policy=True)
    assert out.exists()


def test_enforce_helper_is_noop_for_valid_plan():
    enforce_policy_or_raise(load_mission_plan(VALID))  # must not raise


def test_cli_enforce_denied_exits_nonzero(tmp_path, capsys, monkeypatch):
    from orbital_mission_compiler.cli import main

    out = tmp_path / "cli-out.json"
    monkeypatch.setattr(
        sys, "argv", ["prog", "compile", "--input", DENIED, "--output", str(out), "--enforce-policy"]
    )
    with pytest.raises(SystemExit) as se:
        main()
    assert se.value.code == 1
    assert "denied" in capsys.readouterr().err
    assert not out.exists()  # no artifact on denial


def test_cli_no_enforce_denied_still_succeeds(tmp_path, capsys, monkeypatch):
    from orbital_mission_compiler.cli import main

    out = tmp_path / "cli-out2.json"
    monkeypatch.setattr(sys, "argv", ["prog", "compile", "--input", DENIED, "--output", str(out)])
    main()  # no enforcement -> no SystemExit
    assert out.exists()
