"""Tests for the selectable policy engine (#1) and fail-closed enforcement.

The gate runs through ``evaluate_policy_decision`` with a chosen engine:
- ``opa``     — executes the versioned, auditable Rego bundle (authoritative);
                the default for the artifact-producing CLI commands.
- ``baseline`` — the proven-equivalent in-process mirror (offline/tests).

A selected engine that cannot render a decision (e.g. ``opa`` absent) must fail
CLOSED — raise ``PolicyEngineUnavailableError``, never silently downgrade or skip.
"""

import sys
from pathlib import Path

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
    # #7: the typed {rule,rule_id,severity,provenance,path,message} must survive
    # the enforcement boundary, not be flattened to strings.
    with pytest.raises(compiler.PolicyViolationError) as exc:
        compiler.enforce_policy_or_raise(load_mission_plan(DENIED), engine="baseline")
    v = exc.value.violations[0]
    assert set(v) == {"rule", "rule_id", "severity", "provenance", "path", "message"}
    assert exc.value.messages == [x["message"] for x in exc.value.violations]


# ── Strict decision parsing (PR #77 external review, P1-2 / P1-3) ────────


@pytest.mark.parametrize(
    "value, why",
    [
        ({"allow": False, "violations": []}, "denied but lists nothing"),
        ({"allow": True, "violations": [{"rule": 4, "rule_id": "OMP-004", "severity": "T2",
                                         "provenance": "A", "path": "/x", "message": "m"}]},
         "allowed while listing a violation"),
        ({"violations": ""}, "violations is not a list"),
        ({"violations": ["a bare string"]}, "violation is not a typed object"),
        ({"violations": [{"message": "m"}]}, "violation missing typed fields"),
        ({"allow": "false"}, "allow is a string, and bool('false') is True"),
        ({"deny": "blocked"}, "deny is not a list"),
        ({"result": "something else"}, "carries neither violations nor deny"),
        ("not-an-object", "decision is not an object"),
    ],
)
def test_untrustworthy_decision_fails_closed(value, why):
    """An unreadable or self-contradictory decision must never read as "allowed".

    Returning an empty violation list for these would admit the plan, which is
    the one outcome a fail-closed gate must not reach by accident.
    """
    with pytest.raises(compiler.PolicyEngineUnavailableError):
        compiler.typed_violations_from_decision(value)


def test_consistent_decisions_are_accepted():
    allowed = compiler.typed_violations_from_decision({"allow": True, "violations": []})
    assert allowed == []
    viol = {"rule": 4, "rule_id": "OMP-004", "severity": "T2",
            "provenance": "A", "path": "/x", "message": "m"}
    denied = compiler.typed_violations_from_decision({"allow": False, "violations": [viol]})
    assert denied == [viol]
    # A custom decision exposing only the deny set is projected onto the same shape.
    projected = compiler.typed_violations_from_decision({"deny": ["blocked"]})
    assert len(projected) == 1 and projected[0]["message"] == "blocked"


def test_cmd_policy_exits_2_when_the_decision_is_undecidable(monkeypatch, capsys):
    """The standalone gate must not report success for a result it cannot read."""
    import sys

    from orbital_mission_compiler import cli

    monkeypatch.setattr(cli, "eval_policy", lambda *a, **k: (0, "not json at all"))
    monkeypatch.setattr(sys, "argv", ["prog", "policy", "--input", VALID])
    with pytest.raises(SystemExit) as se:
        cli.main()
    assert se.value.code == 2, "undecidable must be distinct from denied (1) and allowed (0)"
    assert "undecidable" in capsys.readouterr().err


# ── Bundle resolution must not depend on the process CWD (P1-7) ──────────


def test_default_bundle_resolves_from_any_working_directory(tmp_path, monkeypatch):
    """The artifact commands default to the opa engine, so a CWD-relative bundle
    makes the default path fail whenever the tool runs outside the checkout."""
    import os
    import subprocess

    out = tmp_path / "o.json"
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    proc = subprocess.run(
        [sys.executable, "-m", "orbital_mission_compiler.cli", "compile",
         "--input", str(Path(VALID).resolve()), "--output", str(out)],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert out.exists()


def test_installed_wheel_carries_the_policy_bundle(tmp_path):
    """Build a wheel and check the Rego bundle ships inside the package.

    The CLI defaults to the opa engine, so a wheel without the bundle leaves the
    default path unusable anywhere outside a checkout. Resolving from the source
    tree hides that, which is why this inspects the built artifact.
    """
    import importlib.util
    import subprocess
    import zipfile

    # Two different situations that a single skip used to blur together. The
    # tool being absent is environmental and worth skipping for; the build
    # running and failing is the packaging regression this test exists to catch,
    # and skipping on that disarms it on exactly the run that should go red.
    # `build.__main__`, not `build`: a stray build/ directory in the checkout is a
    # namespace package that satisfies the plain name and then fails to execute.
    # find_spec raises rather than returning None when the parent is absent.
    try:
        runnable = importlib.util.find_spec("build.__main__") is not None
    except (ImportError, ValueError):
        runnable = False
    if not runnable:
        pytest.skip("the `build` package is not installed (it is pinned in the dev extra)")

    # Build from an isolated copy of the packaging inputs. Building the checkout
    # in place reuses setuptools' build/ scratch directory, and a wheel assembled
    # from that cache still contains a file the source no longer provides -- so
    # the test passed even with the bundle moved out of the tree.
    import shutil

    repo = Path(__file__).resolve().parents[1]
    workdir = tmp_path / "src-copy"
    workdir.mkdir()
    shutil.copytree(repo / "src", workdir / "src")
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        if (repo / name).exists():
            shutil.copy2(repo / name, workdir / name)
    for stale in workdir.rglob("*.egg-info"):
        shutil.rmtree(stale, ignore_errors=True)

    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path), str(workdir)],
        capture_output=True, text=True,
    )
    # `build` is pinned in the dev extra, so a failure here is a packaging
    # problem, which is the thing this test exists to catch. Skipping on it would
    # disarm the test on exactly the run that should go red.
    assert proc.returncode == 0, f"wheel build failed:\n{proc.stderr[-1500:]}"
    wheels = list(tmp_path.glob("*.whl"))
    assert wheels, "no wheel produced"
    entries = zipfile.ZipFile(wheels[0]).namelist()
    assert "orbital_mission_compiler/policies/mission_plan.rego" in entries, entries


# ── decision self-consistency ─────────────────────────────────────────

def _typed(message: str, rule: int = 4) -> dict:
    return {
        "rule": rule, "rule_id": "OMP-004", "severity": "T1",
        "provenance": "A", "path": "events[0]", "message": message,
    }


def test_deny_and_violations_must_name_the_same_reasons():
    """The bundle defines `deny` as the message projection of `violations`, so a
    decision where the two disagree is not a decision this gate can act on.

    Comparing only emptiness accepts a decision that denies for one reason in
    `deny` and a different one in `violations`, and each consumer then reports
    whichever field it happens to read.
    """
    from orbital_mission_compiler.compiler import (
        PolicyEngineUnavailableError,
        typed_violations_from_decision,
    )

    same = {"allow": False, "deny": ["gpu step needs a fallback"],
            "violations": [_typed("gpu step needs a fallback")]}
    assert len(typed_violations_from_decision(same)) == 1

    for bad in (
        {"allow": False, "deny": ["a different reason"], "violations": [_typed("gpu step needs a fallback")]},
        {"allow": False, "deny": ["one", "two"], "violations": [_typed("one")]},
        {"allow": False, "deny": [], "violations": [_typed("one")]},
    ):
        with pytest.raises(PolicyEngineUnavailableError, match="disagrees with itself"):
            typed_violations_from_decision(bad)


def test_boolean_rule_number_is_not_a_rule_number():
    """`True` passes an isinstance(int) check in Python and would be reported as
    rule 1, so a decision carrying it is rejected rather than renumbered."""
    from orbital_mission_compiler.compiler import (
        PolicyEngineUnavailableError,
        typed_violations_from_decision,
    )

    item = _typed("gpu step needs a fallback")
    item["rule"] = True
    with pytest.raises(PolicyEngineUnavailableError, match="unusable 'rule'"):
        typed_violations_from_decision({"allow": False, "violations": [item]})
