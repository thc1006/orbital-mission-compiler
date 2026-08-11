"""The plan a command renders is the plan its reconciliation scope came from.

Ownership is declared from the input rather than read back off what was
written, which is what lets a revision that renders nothing reconcile at all.
That only holds while there is one input. Both Argo paths read the file twice --
once to derive the scope, once inside the renderer -- so a file edited between
the two reads publishes one plan's manifests under another plan's scope.

`_load_or_accept_plan` exists for exactly this: a caller that judged a plan can
render the object it judged rather than handing the path back.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from orbital_mission_compiler import cli, compiler
from orbital_mission_compiler.cli import build_parser, cmd_render_argo, cmd_render_kueue

PLAN = "configs/mission_plans/demo_gpu_fallback_fixed.yaml"
OTHER = "configs/mission_plans/sample_download_only.yaml"


def _count_reads(monkeypatch) -> dict:
    """Count how often a command goes back to the file for the plan."""
    seen = {"n": 0}
    real = compiler.load_mission_plan

    def counting(path):
        seen["n"] += 1
        return real(path)

    monkeypatch.setattr(compiler, "load_mission_plan", counting)
    monkeypatch.setattr(cli, "load_mission_plan", counting)
    return seen


@pytest.mark.parametrize(
    "argv_extra,label",
    [([], "ungated"), (["--argo-lint"], "gated")],
)
def test_render_argo_reads_the_plan_once(argv_extra, label, tmp_path, monkeypatch, capsys):
    """One read, so the scope and the render cannot describe different plans."""
    from tests.test_argo_lint_gate import _fake_argo

    out = tmp_path / "out"
    argv = [
        "render-argo", "--input", PLAN, "--output-dir", str(out),
        "--policy-engine", "baseline", "--prune", *argv_extra,
    ]
    if argv_extra:
        argv += ["--argo-bin", str(_fake_argo(tmp_path, 0))]
    seen = _count_reads(monkeypatch)

    cmd_render_argo(build_parser().parse_args(argv))
    capsys.readouterr()

    assert seen["n"] == 1, f"{label} read the plan {seen['n']} times"


def test_render_kueue_reads_the_plan_once(tmp_path, monkeypatch, capsys):
    """Already true, and pinned so it stays that way."""
    out = tmp_path / "out"
    seen = _count_reads(monkeypatch)

    cmd_render_kueue(build_parser().parse_args([
        "render-kueue", "--input", PLAN, "--output-dir", str(out),
        "--policy-engine", "baseline", "--prune",
    ]))
    capsys.readouterr()

    assert seen["n"] == 1, f"read the plan {seen['n']} times"


@pytest.mark.parametrize(
    "argv_extra,label",
    [([], "ungated"), (["--argo-lint"], "gated")],
)
def test_a_plan_replaced_mid_run_does_not_split_the_render_from_its_scope(
    argv_extra, label, tmp_path, monkeypatch, capsys
):
    """The failure the second read allowed.

    Swapping the file for a different mission between the scope read and the
    renderer's own read produced manifests for one mission reconciled under the
    other's scope. With one read the swap cannot land between them, so whichever
    plan the command took, it renders and reconciles the same one.
    """
    from tests.test_argo_lint_gate import _fake_argo

    plan = tmp_path / "plan.yaml"
    plan.write_text(Path(PLAN).read_text(encoding="utf-8"), encoding="utf-8")
    out = tmp_path / "out"
    argv = [
        "render-argo", "--input", str(plan), "--output-dir", str(out),
        "--policy-engine", "baseline", "--prune", *argv_extra,
    ]
    if argv_extra:
        argv += ["--argo-bin", str(_fake_argo(tmp_path, 0))]

    real = compiler.load_mission_plan
    swapped = {"done": False}

    def swap_after_first(path):
        result = real(path)
        if not swapped["done"]:
            swapped["done"] = True
            plan.write_text(Path(OTHER).read_text(encoding="utf-8"), encoding="utf-8")
        return result

    monkeypatch.setattr(compiler, "load_mission_plan", swap_after_first)
    monkeypatch.setattr(cli, "load_mission_plan", swap_after_first)

    cmd_render_argo(build_parser().parse_args(argv))
    report = json.loads(capsys.readouterr().out)

    written = [Path(p).name for p in report.get("files", [])]
    assert written, report
    missions = {
        (yaml.safe_load((out / name).read_text(encoding="utf-8")) or {})
        .get("metadata", {}).get("labels", {}).get("mission-id")
        for name in written
    }
    # One mission, and the one the first read took.
    assert missions == {"demo-gpu-fallback-fixed"}, (missions, report)
