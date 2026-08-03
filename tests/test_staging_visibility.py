"""What a reader of the output directory can see while a render is in flight.

`kubectl apply -R -f <dir>` descends into directories whose names begin with a
dot and picks up dotted files at the top level too, measured on v1.36.3. So
staging named `.argo-lint-staging-*` inside the output directory is not hidden
from the consumer at all: a recursive apply during a gated render collects
manifests the linter has not passed yet, and a backup left behind by a failed
cleanup is a second copy of the previous generation sitting where it will be
applied.

Observed from the reader's position rather than from the implementation's: the
linter is where the gate is holding a verdict it has not given, so that is the
moment to look at the directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from orbital_mission_compiler import cli
from orbital_mission_compiler.cli import build_parser, cmd_render_argo, cmd_render_kueue

PLAN = "configs/mission_plans/demo_gpu_fallback_fixed.yaml"


def _snapshot_at_lint(monkeypatch, out_dir: Path) -> list[list[str]]:
    """Everything in the output directory each time the linter is invoked."""
    seen: list[list[str]] = []
    real = cli.argo_lint_path

    def watching(staging, **kwargs):
        seen.append(sorted(p.name for p in out_dir.iterdir()) if out_dir.exists() else [])
        return real(staging, **kwargs)

    monkeypatch.setattr(cli, "argo_lint_path", watching)
    return seen


def test_a_gated_render_puts_no_staging_in_the_published_directory(
    tmp_path, monkeypatch, capsys
):
    """The directory a consumer reads holds only published manifests.

    Checked while the linter runs, which is precisely when the gate is holding a
    verdict it has not given and the staged copies exist.
    """
    from tests.test_argo_lint_gate import _fake_argo

    out = tmp_path / "out"
    out.mkdir()
    (out / "pre-existing.yaml").write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: already-here\n", encoding="utf-8"
    )
    seen = _snapshot_at_lint(monkeypatch, out)

    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", PLAN, "--output-dir", str(out),
        "--policy-engine", "baseline", "--argo-lint",
        "--argo-bin", str(_fake_argo(tmp_path, 0)),
    ]))
    capsys.readouterr()

    assert seen, "the linter never ran, so nothing was observed"
    for listing in seen:
        assert listing == ["pre-existing.yaml"], listing


def test_publishing_puts_no_backup_in_the_published_directory(tmp_path, monkeypatch, capsys):
    """The previous generation is set aside outside what a consumer reads.

    A backup inside the output is a full second copy of the last generation, and
    `kubectl apply` picks up a dotted file at the top level, so a cleanup that
    fails leaves the old manifests to be applied alongside the new ones.
    """
    from tests.test_argo_lint_gate import _fake_argo

    out = tmp_path / "out"
    # The gated path, because it is the one that publishes through a backup. The
    # ungated path writes straight into the directory and takes no backup at all,
    # which is its own gap and not this one.
    argv = [
        "render-argo", "--input", PLAN, "--output-dir", str(out),
        "--policy-engine", "baseline", "--argo-lint",
        "--argo-bin", str(_fake_argo(tmp_path, 0)),
    ]
    cmd_render_argo(build_parser().parse_args(argv))
    capsys.readouterr()

    # Snapshotted just before the backup is discarded, which is the window it
    # exists in. Looking afterwards sees a cleaned-up directory and proves
    # nothing about what a reader could have collected.
    seen: list[list[str]] = []
    real_discard = cli._discard_backup

    def watching(backup_dir, leftover=None):
        seen.append(sorted(p.name for p in out.iterdir()) if out.exists() else [])
        return real_discard(backup_dir, leftover)

    monkeypatch.setattr(cli, "_discard_backup", watching)
    cmd_render_argo(build_parser().parse_args(argv))
    capsys.readouterr()

    assert seen, "no backup was ever taken, so nothing was observed"
    for listing in seen:
        assert not [n for n in listing if n.startswith(".")], listing


def test_render_kueue_stages_outside_the_published_directory(tmp_path, monkeypatch, capsys):
    """The other writer stages too, into the same directory consumers read."""
    out = tmp_path / "out"
    out.mkdir()
    # Observed on entry to the publish step, when the staged copies exist and
    # nothing has been moved into place yet.
    seen: list[list[str]] = []
    real_publish = cli._publish

    def watching(staged, out_dir, leftover=None, staging_dir=None):
        seen.append(sorted(p.name for p in out_dir.iterdir()) if out_dir.exists() else [])
        return real_publish(staged, out_dir, leftover, staging_dir)

    monkeypatch.setattr(cli, "_publish", watching)
    cmd_render_kueue(build_parser().parse_args([
        "render-kueue", "--input", PLAN, "--output-dir", str(out),
        "--policy-engine", "baseline",
    ]))
    capsys.readouterr()

    assert seen, "the publish step never ran, so nothing was observed"
    for listing in seen:
        assert not [n for n in listing if n.startswith(".")], listing


def test_a_rejected_render_still_leaves_an_absent_directory_absent(tmp_path, capsys):
    """The constraint the old placement existed for, which has to survive.

    Staging cannot be created by first creating the output directory: a denied
    plan or a rejected lint must leave a path that did not exist exactly as it
    was.
    """
    from tests.test_argo_lint_gate import _fake_argo

    out = tmp_path / "never" / "created"
    with pytest.raises(SystemExit):
        cmd_render_argo(build_parser().parse_args([
            "render-argo", "--input", PLAN, "--output-dir", str(out),
            "--policy-engine", "baseline", "--argo-lint",
            "--argo-bin", str(_fake_argo(tmp_path, 1)),
        ]))
    capsys.readouterr()

    assert not out.exists()


def test_a_staging_dir_the_caller_names_is_used(tmp_path, monkeypatch, capsys):
    """For an output directory whose parent is on another filesystem.

    Publishing is a rename, so staging has to share a filesystem with the
    output. When the output is a mount point its parent does not, and only the
    operator knows where else on that filesystem to put it.
    """
    from tests.test_argo_lint_gate import _fake_argo

    out = tmp_path / "out"
    out.mkdir()
    staging_root = tmp_path / "elsewhere"
    staging_root.mkdir()
    before = set(os.listdir(staging_root))
    seen: list[list[str]] = []
    real_lint = cli.argo_lint_path

    def watching(staging, **kwargs):
        seen.append(sorted(p.name for p in staging_root.iterdir()))
        return real_lint(staging, **kwargs)

    monkeypatch.setattr(cli, "argo_lint_path", watching)

    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", PLAN, "--output-dir", str(out),
        "--policy-engine", "baseline", "--staging-dir", str(staging_root),
        "--argo-lint", "--argo-bin", str(_fake_argo(tmp_path, 0)),
    ]))
    capsys.readouterr()

    assert list(out.glob("*.yaml")), "the render still has to publish"
    assert set(os.listdir(staging_root)) == before, "staging is cleaned up after itself"
    # Emptiness afterwards is true whether or not the flag was read, so what
    # says it was read is that the directory held the staged set while the
    # linter was looking at it.
    assert any(during for during in seen), (
        "nothing was ever staged in the directory the flag named"
    )


@pytest.mark.parametrize("value", ["relative/dir", "./x"], ids=["bare", "dot"])
def test_a_relative_staging_dir_is_refused(value, capsys):
    """Same reason as the lock directory: resolved against whichever working
    directory this process happens to be in, which is not a location."""
    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "render-argo", "--input", PLAN, "--output-dir", "out",
            "--staging-dir", value,
        ])
    assert "is relative" in capsys.readouterr().err


def test_an_output_on_its_own_filesystem_refuses_rather_than_staging_inside(
    tmp_path, monkeypatch, capsys
):
    """No rename crosses a mount boundary, and falling back inside is the harm.

    Staging inside the output is what a consumer reads, so quietly doing that
    when the parent is elsewhere would trade a visible failure for an invisible
    exposure. Only the operator knows what else lives on that filesystem.
    """
    from tests.test_argo_lint_gate import _fake_argo

    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(cli, "_same_filesystem", lambda a, b: False)

    # Driven through main(), because the promise of one report and a documented
    # exit code is made there.
    monkeypatch.setattr("sys.argv", [
        "orbital-mission-compiler", "render-argo", "--input", PLAN,
        "--output-dir", str(out), "--policy-engine", "baseline", "--argo-lint",
        "--argo-bin", str(_fake_argo(tmp_path, 0)),
    ])
    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    report = json.loads(captured.err)
    assert report["reason"] == "staging_unavailable", report
    assert "--staging-dir" in report["hint"], report
    assert not [p.name for p in out.iterdir()], "nothing may be staged or published"
