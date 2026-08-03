"""What every command promises when the plan it was given cannot be used.

The commands promise a machine-readable report and a documented exit code, and
callers branch on both: `validate_live_cluster.sh` reads the JSON, and the gated
render distinguishes "rejected" (1) from "could not run" (2). An input the
compiler cannot take escaped both -- a traceback, an empty stdout, and exit 1,
which in the gated path is the code that means the linter rejected something.

Split where the compiler's own answer splits. A file it cannot read is a run
that never started, which is the family `policy_engine_unavailable` is in and
exits 2. A file it read and refused is a verdict, which is the family a policy
denial is in and exits 1.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from orbital_mission_compiler.cli import main

GOOD_PLAN = Path("configs/mission_plans/sample_maritime_surveillance.yaml")

# Reading a mode-000 file succeeds for root, so the shape under test does not
# exist there. Skipped rather than quietly asserted, which would pass for the
# wrong reason wherever tests run in a root container.
_IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def _plan(tmp_path: Path, shape: str) -> Path:
    target = tmp_path / f"{shape}.yaml"
    if shape == "missing":
        return tmp_path / "no-such-plan.yaml"
    if shape == "directory":
        target.mkdir()
    elif shape == "unreadable":
        target.write_text(GOOD_PLAN.read_text(encoding="utf-8"), encoding="utf-8")
        target.chmod(0o000)
    elif shape == "dangling link":
        target.symlink_to(tmp_path / "nothing-here.yaml")
    elif shape == "unparseable":
        target.write_text("events:\n  - [unclosed\n", encoding="utf-8")
    elif shape == "not a mapping":
        target.write_text("- just\n- a\n- list\n", encoding="utf-8")
    elif shape == "empty":
        target.write_text("", encoding="utf-8")
    elif shape == "schema invalid":
        target.write_text("mission_id: x\nevents: []\n", encoding="utf-8")
    else:  # pragma: no cover - a shape added to the table and not to the builder
        raise AssertionError(f"unknown shape {shape!r}")
    return target


def _argv(command: str, plan: Path, out: Path) -> list[str]:
    common = ["--input", str(plan), "--policy-engine", "baseline"]
    if command == "render-argo":
        return ["render-argo", *common, "--output-dir", str(out)]
    if command == "render-argo --argo-lint":
        return ["render-argo", *common, "--output-dir", str(out), "--argo-lint"]
    if command == "render-kueue":
        return ["render-kueue", *common, "--output-dir", str(out)]
    if command == "compile":
        return ["compile", *common, "--output", str(out / "compiled.json")]
    if command == "inspect":
        return ["inspect", "--input", str(plan)]
    raise AssertionError(f"unknown command {command!r}")  # pragma: no cover


COMMANDS = [
    "render-argo",
    "render-argo --argo-lint",
    "render-kueue",
    "compile",
    "inspect",
]
UNREADABLE = ["missing", "directory", "unreadable", "dangling link"]
INVALID = ["unparseable", "not a mapping", "empty", "schema invalid"]


def _run(monkeypatch, capsys, command: str, plan: Path, out: Path):
    monkeypatch.setattr("sys.argv", ["orbital-mission-compiler", *_argv(command, plan, out)])
    with pytest.raises(SystemExit) as excinfo:
        main()
    captured = capsys.readouterr()
    return excinfo.value.code, captured


def _sole_document(captured) -> dict:
    """The report, wherever the command puts it, and only one of them."""
    streams = [s for s in (captured.out, captured.err) if s.strip()]
    assert len(streams) == 1, f"expected one stream to carry the report, got {captured}"
    return json.loads(streams[0])


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("shape", UNREADABLE)
def test_a_plan_that_cannot_be_read_is_a_run_that_never_started(
    command, shape, tmp_path, monkeypatch, capsys
):
    """Exit 2, the code for a command that could not run.

    Exit 1 would collide with the gated render's meaning for it, so a caller
    branching on the contract read a permission error as a lint rejection.
    """
    if shape == "unreadable" and _IS_ROOT:
        pytest.skip("mode 000 does not stop root reading the file")
    plan = _plan(tmp_path, shape)
    out = tmp_path / "out"
    out.mkdir()

    code, captured = _run(monkeypatch, capsys, command, plan, out)

    assert code == 2, captured
    report = _sole_document(captured)
    assert report["status"] == "error", report
    assert report["reason"] == "input_unreadable", report
    assert str(plan) in report["error"], report


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("shape", INVALID)
def test_a_file_that_is_not_a_plan_is_a_verdict(
    command, shape, tmp_path, monkeypatch, capsys
):
    """Exit 1, the code a policy denial already uses.

    The compiler read the file and refused it, which is the same kind of answer
    as the policy layer refusing a plan it understood.
    """
    plan = _plan(tmp_path, shape)
    out = tmp_path / "out"
    out.mkdir()

    code, captured = _run(monkeypatch, capsys, command, plan, out)

    assert code == 1, captured
    report = _sole_document(captured)
    assert report["status"] == "error", report
    assert report["reason"] == "input_invalid", report
    assert str(plan) in report["error"], report


@pytest.mark.parametrize("command", ["render-argo", "render-argo --argo-lint", "render-kueue"])
@pytest.mark.parametrize("shape", UNREADABLE + INVALID)
def test_a_rejected_input_leaves_the_output_directory_untouched(
    command, shape, tmp_path, monkeypatch, capsys
):
    """Fail closed, and fail closed before anything exists to clean up.

    The report is only half of it. The gated render makes its staging directory
    under the output directory when that already exists, so refusing the plan
    after that point leaves a `.argo-lint-staging-*` in an operator's output for
    a run that reported doing nothing. Reading the plan first is what keeps the
    report and the directory agreeing.
    """
    if shape == "unreadable" and _IS_ROOT:
        pytest.skip("mode 000 does not stop root reading the file")
    plan = _plan(tmp_path, shape)
    out = tmp_path / "out"
    out.mkdir()

    _run(monkeypatch, capsys, command, plan, out)

    assert sorted(p.name for p in out.iterdir()) == []


def test_the_duplicate_key_refusal_still_names_the_duplicate(tmp_path):
    """The wrapping must not hide what the strict loader found.

    A duplicate key is the one parse failure this repo has a test for elsewhere,
    because it is the one that silently keeps a random one of the two values.
    """
    from orbital_mission_compiler.compiler import load_mission_plan

    plan = tmp_path / "dupes.yaml"
    plan.write_text("mission_id: a\nmission_id: b\n", encoding="utf-8")

    with pytest.raises(Exception, match="duplicate key"):
        load_mission_plan(plan)
