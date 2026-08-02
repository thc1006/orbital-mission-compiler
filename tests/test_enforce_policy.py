"""Effective tests for the fail-closed policy admission gate.

The file-level compile/render entrypoints (and the CLI/MCP that drive them) are
fail-closed BY DEFAULT: a plan the policy layer would deny produces NO artifact and
a non-zero CLI exit. This realizes the paper's claim that "the compiler enforces
four independent checks on every mission plan before any artifact is admitted."
An explicit escape hatch (enforce_policy=False / --unsafe-skip-policy) preserves the
composable-stage use, matching the paper's own bypass caveat.

Every test here is designed to FAIL if the implementation regresses:
- the block tests assert the surfaced violations EQUAL the policy layer's output
  (a stub that raised an empty error would fail),
- the default-blocks tests assert a denied plan does NOT render by default (an
  opt-in / fail-open regression fails here),
- the compile_file test asserts NO output file is written (a write-then-raise fails),
- the skip tests assert the explicit opt-out still renders a denied plan.
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
    assert exc.value.messages == _policy_violations(DENIED)
    assert "detect-ships" in str(exc.value)


def test_default_blocks_a_denied_plan():
    # Fail-closed default: the denied plan does NOT render unless explicitly skipped.
    # An opt-in / fail-open regression would fail here.
    with pytest.raises(PolicyViolationError) as exc:
        render_workflows_for_file(DENIED)
    assert exc.value.messages == _policy_violations(DENIED)


def test_explicit_skip_renders_a_denied_plan():
    # The escape hatch (enforce_policy=False) preserves the composable-stage use:
    # a caller that explicitly opts out still renders a denied plan.
    workflows = render_workflows_for_file(DENIED, enforce_policy=False)
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


def test_denied_run_leaves_preexisting_artifact_untouched(tmp_path):
    # Stale-output contract: on denial NO new artifact is written and a file that
    # already exists at the output path is left exactly as-is (not overwritten,
    # not truncated). A correct consumer keys on the non-zero exit / raised error,
    # NOT on file existence -- otherwise a stale artifact could be mistaken for
    # fresh output. (We deliberately do NOT delete a prior valid artifact.)
    out = tmp_path / "out.json"
    out.write_text("STALE-BUT-VALID-FROM-A-PRIOR-RUN")
    with pytest.raises(PolicyViolationError):
        compile_file(DENIED, out, enforce_policy=True)
    assert out.read_text() == "STALE-BUT-VALID-FROM-A-PRIOR-RUN"


def test_compile_file_enforce_valid_writes_artifact(tmp_path):
    out = tmp_path / "out.json"
    compile_file(VALID, out, enforce_policy=True)
    assert out.exists()


def test_enforce_helper_is_noop_for_valid_plan():
    enforce_policy_or_raise(load_mission_plan(VALID))  # must not raise


def test_cli_denied_blocks_by_default(tmp_path, capsys, monkeypatch):
    from orbital_mission_compiler.cli import main

    # No flag: the CLI is fail-closed by default -> exit 1, no artifact.
    out = tmp_path / "cli-out.json"
    # Use the always-available baseline engine so this enforcement test runs
    # without opa; a separate opa-guarded test covers the opa-default path.
    monkeypatch.setattr(
        sys, "argv",
        ["prog", "compile", "--input", DENIED, "--output", str(out), "--policy-engine", "baseline"],
    )
    with pytest.raises(SystemExit) as se:
        main()
    assert se.value.code == 1
    err = capsys.readouterr().err
    assert "denied" in err
    assert "--unsafe-skip-policy" in err  # the denial surfaces the opt-out
    assert not out.exists()  # no artifact on denial


def test_cli_unsafe_skip_policy_renders_denied(tmp_path, capsys, monkeypatch):
    from orbital_mission_compiler.cli import main

    # Explicit opt-out: the denied plan compiles and writes an artifact.
    out = tmp_path / "cli-out2.json"
    monkeypatch.setattr(
        sys, "argv", ["prog", "compile", "--input", DENIED, "--output", str(out), "--unsafe-skip-policy"]
    )
    main()  # opt-out -> no SystemExit
    assert out.exists()
