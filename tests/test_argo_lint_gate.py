"""The opt-in fail-closed ``argo lint`` gate on ``render-argo``.

Layer (iii) of the layered defensive validation: a static lint of the rendered
Argo YAML, after schema (i) and policy (ii). The gate is off by default so the
Argo CLI stays optional; once requested it never degrades to a skip.

Two outcomes have to stay distinct. A manifest Argo rejects is a verdict, and
exits 1. A gate that could not run at all -- CLI absent, timeout, killed, or
nothing rendered to lint -- produced no verdict, and exits 2. Collapsing them
would let "the linter never ran" read as "this manifest is invalid", or worse,
as a pass.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from orbital_mission_compiler.cli import build_parser, cmd_render_argo
from orbital_mission_compiler.compiler import ArgoLintUnavailable, argo_lint_path

VALID_PLAN = "configs/mission_plans/sample_maritime_surveillance.yaml"
ARGO_AVAILABLE = subprocess.run(  # noqa: S603
    ["sh", "-c", "command -v argo"], capture_output=True
).returncode == 0


def _fake_argo(tmp_path: Path, exit_code: int, name: str = "argo", body: str = "") -> Path:
    """A stand-in for the CLI, so these tests need no real Argo install."""
    exe = tmp_path / name
    exe.write_text(
        "#!/bin/sh\n"
        '# record what the gate actually invoked, so the flags are assertable\n'
        f'printf "%s\\n" "$*" > "{tmp_path}/argv.txt"\n'
        f"{body}\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


def _run(tmp_path, monkeypatch, *extra, out_name="out"):
    out = tmp_path / out_name
    argv = ["prog", "render-argo", "--input", VALID_PLAN, "--output-dir", str(out), *extra]
    monkeypatch.setattr(sys, "argv", argv)
    args = build_parser().parse_args(argv[1:])
    return args, out


# ── the helper's error model ─────────────────────────────────────────


def test_missing_cli_is_unavailable_not_a_lint_failure(tmp_path):
    with pytest.raises(ArgoLintUnavailable, match="not found on PATH"):
        argo_lint_path(tmp_path, argo_bin="argo-does-not-exist-xyz")


def test_a_file_without_the_executable_bit_is_unavailable(tmp_path):
    exe = tmp_path / "argo"
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")  # no chmod
    with pytest.raises(ArgoLintUnavailable):
        argo_lint_path(tmp_path, argo_bin=str(exe))


def test_timeout_is_unavailable_not_a_verdict(tmp_path):
    """A timeout says nothing about the manifest. Reporting it as a lint
    failure would be a verdict the linter never reached."""
    exe = _fake_argo(tmp_path, 0, body="sleep 5")
    with pytest.raises(ArgoLintUnavailable, match="timed out"):
        argo_lint_path(tmp_path, argo_bin=str(exe), timeout=1)


def test_a_signalled_process_is_unavailable(tmp_path):
    """A process killed by a signal reports a negative return code, which is
    not an Argo exit status at all."""
    exe = _fake_argo(tmp_path, 0, body="kill -TERM $$")
    with pytest.raises(ArgoLintUnavailable, match="signal"):
        argo_lint_path(tmp_path, argo_bin=str(exe))


def test_lint_runs_offline_over_the_directory(tmp_path):
    """Offline, uncoloured, machine-readable, and one directory argument.

    A per-file argument list is unbounded in the number of rendered workflows,
    and passing the directory also covers whatever is already in it.
    """
    exe = _fake_argo(tmp_path, 0)
    target = tmp_path / "manifests"
    target.mkdir()
    rc, _ = argo_lint_path(target, argo_bin=str(exe))
    assert rc == 0
    argv = (tmp_path / "argv.txt").read_text(encoding="utf-8").split()
    assert argv[0] == "lint"
    assert "--offline" in argv and "--no-color" in argv
    assert argv[-1] == str(target)


# ── the CLI gate ─────────────────────────────────────────────────────


def test_gate_off_by_default_does_not_invoke_the_cli(tmp_path, monkeypatch, capsys):
    """Without the flag the Argo CLI is not consulted at all, so it stays
    optional for local and portable use."""
    exe = _fake_argo(tmp_path, 1)  # would fail the gate if it ever ran
    args, out = _run(tmp_path, monkeypatch, "--argo-bin", str(exe))
    cmd_render_argo(args)
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "ok" and "lint" not in data
    assert list(out.glob("*.yaml"))
    assert not (tmp_path / "argv.txt").exists(), "the linter was invoked without --argo-lint"


def test_gate_publishes_only_after_a_clean_lint(tmp_path, monkeypatch, capsys):
    exe = _fake_argo(tmp_path, 0)
    args, out = _run(tmp_path, monkeypatch, "--argo-lint", "--argo-bin", str(exe))
    cmd_render_argo(args)
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "ok" and data["lint"] == "passed"
    assert data["files"] and all(Path(f).exists() for f in data["files"])
    assert all(Path(f).parent == out for f in data["files"])


def test_a_lint_failure_leaves_the_output_directory_untouched(tmp_path, monkeypatch, capsys):
    """The gate has to be a gate. Writing the manifests and reporting the
    failure afterwards leaves output no lint stage accepted where a caller that
    ignores the exit code will apply it.
    """
    exe = _fake_argo(tmp_path, 1, body='echo "in \\"wf\\": template undefined"')
    args, out = _run(tmp_path, monkeypatch, "--argo-lint", "--argo-bin", str(exe))
    out.mkdir(parents=True)
    survivor = out / "previous-good.yaml"
    survivor.write_text("kind: Workflow\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        cmd_render_argo(args)
    assert exc.value.code == 1
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "lint-failed"
    assert data["files"] == []
    assert "template undefined" in data["lint_output"]
    # Nothing new landed, and the render that did pass is still there.
    assert [p.name for p in out.glob("*.yaml")] == ["previous-good.yaml"]
    assert survivor.read_text(encoding="utf-8") == "kind: Workflow\n"
    # No staging directory left behind either.
    assert not list(tmp_path.glob(".argo-lint-staging-*"))


def test_gate_fails_closed_when_the_cli_is_absent(tmp_path, monkeypatch, capsys):
    args, out = _run(tmp_path, monkeypatch, "--argo-lint", "--argo-bin", "argo-nope-xyz")
    with pytest.raises(SystemExit) as exc:
        cmd_render_argo(args)
    assert exc.value.code == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "error" and data["lint"] == "unavailable"
    assert not out.exists() or not list(out.glob("*.yaml"))


def test_a_plan_that_renders_nothing_cannot_report_a_pass(tmp_path, monkeypatch, capsys):
    """A download-only plan is schema-valid, passes the policy layer, and
    renders no Workflow. Treating an empty render as vacuously clean reports a
    lint that never ran, and previously skipped the CLI check with it.
    """
    plan = tmp_path / "download-only.yaml"
    plan.write_text(
        "mission_id: m\n"
        "events:\n"
        "  - timestamp: '2026-08-01T00:00:00Z'\n"
        "    event_type: download\n"
        "    instrument: cam\n"
        "    duration_seconds: 60\n"
        "    ground_visibility: true\n",
        encoding="utf-8",
    )
    exe = _fake_argo(tmp_path, 0)
    out = tmp_path / "out"
    args = build_parser().parse_args([
        "render-argo", "--input", str(plan), "--output-dir", str(out),
        "--argo-lint", "--argo-bin", str(exe),
    ])
    with pytest.raises(SystemExit) as exc:
        cmd_render_argo(args)
    assert exc.value.code == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "error" and data["reason"] == "no-manifests"
    assert data.get("lint") != "passed"


def test_missing_cli_is_reported_even_when_nothing_would_render(tmp_path, monkeypatch, capsys):
    """The CLI check must not be reachable only through a non-empty render."""
    plan = tmp_path / "download-only.yaml"
    plan.write_text(
        "mission_id: m\n"
        "events:\n"
        "  - timestamp: '2026-08-01T00:00:00Z'\n"
        "    event_type: download\n"
        "    instrument: cam\n"
        "    duration_seconds: 60\n"
        "    ground_visibility: true\n",
        encoding="utf-8",
    )
    args = build_parser().parse_args([
        "render-argo", "--input", str(plan), "--output-dir", str(tmp_path / "o"),
        "--argo-lint", "--argo-bin", "argo-nope-xyz",
    ])
    with pytest.raises(SystemExit) as exc:
        cmd_render_argo(args)
    assert exc.value.code == 2
    assert json.loads(capsys.readouterr().out)["lint"] == "unavailable"


def test_a_timeout_exits_2_not_1(tmp_path, monkeypatch, capsys):
    exe = _fake_argo(tmp_path, 0, body="sleep 5")
    monkeypatch.setattr("orbital_mission_compiler.cli.argo_lint_path",
                        lambda *a, **k: (_ for _ in ()).throw(ArgoLintUnavailable("argo lint timed out after 1s")))
    args, _ = _run(tmp_path, monkeypatch, "--argo-lint", "--argo-bin", str(exe))
    with pytest.raises(SystemExit) as exc:
        cmd_render_argo(args)
    assert exc.value.code == 2
    assert json.loads(capsys.readouterr().out)["lint"] == "unavailable"


# ── the stdout contract ──────────────────────────────────────────────


def test_stdout_stays_one_json_document(tmp_path, monkeypatch, capsys):
    """`render-argo` stdout is machine-readable; existing callers run
    json.loads over the whole of it. Printing the linter's own output first
    would break every one of them, so it goes in a field.
    """
    exe = _fake_argo(tmp_path, 0, body='echo "no linting errors found"')
    args, _ = _run(tmp_path, monkeypatch, "--argo-lint", "--argo-bin", str(exe))
    cmd_render_argo(args)
    out = capsys.readouterr().out
    data = json.loads(out)  # the whole stream, not a fragment of it
    assert data["lint"] == "passed"
    assert "no linting errors found" in data["lint_output"]


# ── against the real CLI ─────────────────────────────────────────────


@pytest.mark.skipif(not ARGO_AVAILABLE, reason="argo CLI not installed")
def test_real_argo_accepts_a_rendered_plan(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KUBECONFIG", str(tmp_path / "nonexistent"))
    args, out = _run(tmp_path, monkeypatch, "--argo-lint")
    cmd_render_argo(args)
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "ok" and data["lint"] == "passed"
    assert all(Path(f).exists() for f in data["files"])


@pytest.mark.skipif(not ARGO_AVAILABLE, reason="argo CLI not installed")
def test_real_argo_accepts_the_dra_multi_doc_bundle(tmp_path, monkeypatch, capsys):
    """The bundle an operator applies is multi-document. argo lint reads the
    Workflow out of it and ignores the ResourceClaimTemplate, so this pins that
    the extra document does not break the gate.
    """
    monkeypatch.setenv("KUBECONFIG", str(tmp_path / "nonexistent"))
    out = tmp_path / "dra"
    args = build_parser().parse_args([
        "render-argo", "--input", "configs/mission_plans/sample_gpu_cpu_fallback.yaml",
        "--output-dir", str(out), "--argo-lint", "--dra-fallback", "--namespace", "ns",
    ])
    cmd_render_argo(args)
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "ok" and data["lint"] == "passed"
    import yaml as _yaml
    kinds = set()
    for f in data["files"]:
        kinds |= {d["kind"] for d in _yaml.safe_load_all(Path(f).read_text()) if d}
    assert {"Workflow", "ResourceClaimTemplate"} <= kinds, kinds


@pytest.mark.skipif(not ARGO_AVAILABLE, reason="argo CLI not installed")
def test_real_argo_rejects_a_broken_manifest(tmp_path):
    """Proof the gate is not theatre: the real linter has to reject something."""
    target = tmp_path / "manifests"
    target.mkdir()
    (target / "broken.yaml").write_text(
        "apiVersion: argoproj.io/v1alpha1\n"
        "kind: Workflow\n"
        "metadata:\n  name: broken\n"
        "spec:\n  entrypoint: does-not-exist\n"
        "  templates:\n  - name: main\n    container:\n      image: busybox\n",
        encoding="utf-8",
    )
    env_kubeconfig = os.environ.get("KUBECONFIG")
    os.environ["KUBECONFIG"] = str(tmp_path / "nonexistent")
    try:
        rc, output = argo_lint_path(target)
    finally:
        if env_kubeconfig is None:
            os.environ.pop("KUBECONFIG", None)
        else:
            os.environ["KUBECONFIG"] = env_kubeconfig
    assert rc != 0, output
    assert "does-not-exist" in output
