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
from orbital_mission_compiler.compiler import (
    ArgoLintUnavailable,
    PolicyViolationError,
    argo_lint_path,
)

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



def _multi_service_plan(tmp_path: Path, service_ids) -> Path:
    services = "".join(
        f"      - service_id: {sid}\n"
        f"        priority: 50\n"
        f"        steps:\n"
        f"          - name: s\n"
        f"            image: busybox:1.36\n"
        f"            resource_class: cpu\n"
        for sid in service_ids
    )
    plan = tmp_path / f"plan-{len(list(service_ids))}.yaml"
    plan.write_text(
        "mission_id: m\n"
        "events:\n"
        "  - timestamp: '2026-08-01T00:00:00Z'\n"
        "    event_type: acquisition\n"
        "    instrument: cam\n"
        "    duration_seconds: 60\n"
        "    services:\n" + services,
        encoding="utf-8",
    )
    return plan


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


# ── the publish boundary ─────────────────────────────────────────────


def test_a_failure_part_way_through_publishing_rolls_the_whole_set_back(tmp_path, monkeypatch, capsys):
    """Each rename is atomic; the set a caller applies is not.

    Without a rollback the directory ends up holding some files from this render
    and some from the last one, each individually lint-clean, with nothing
    recording that it is not any one render's output. The previous contents here
    are a real earlier render of the same mission, so the ownership preflight
    passes and this exercises the rollback rather than being stopped before it.
    """
    out = tmp_path / "out"
    exe = _fake_argo(tmp_path, 0)

    def render_args(plan):
        return build_parser().parse_args([
            "render-argo", "--input", str(plan), "--output-dir", str(out),
            "--argo-lint", "--argo-bin", str(exe),
        ])

    # The first render covers b and c; the second adds a. Rollback then has both
    # halves to undo -- a file it created, and two it displaced -- where a run
    # that only displaced would be restored by the displacement alone and would
    # not notice a missing unlink.
    cmd_render_argo(render_args(_multi_service_plan(tmp_path, ["b", "c"])))
    capsys.readouterr()
    previous = {p.name: p.read_text(encoding="utf-8") for p in out.glob("*.yaml")}
    assert len(previous) == 2
    args = render_args(_multi_service_plan(tmp_path, ["a", "b", "c"]))

    real_replace = os.replace
    calls = {"n": 0}

    def failing_replace(src, dst):
        # a publishes (1); b is displaced (2) and published (3); c is displaced
        # (4) -> fail. By then a new file and a replaced one are both in place.
        calls["n"] += 1
        if calls["n"] == 4:
            raise OSError(13, "Permission denied")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(SystemExit) as exc:
        cmd_render_argo(args)
    assert exc.value.code == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "error" and data["reason"] == "publish-failed"

    monkeypatch.undo()
    restored = {p.name: p.read_text(encoding="utf-8") for p in out.glob("*.yaml")}
    assert restored == previous, "the directory was left holding a mixture"
    assert not any("-a-" in name for name in restored), (
        "a file this render added survived the rollback"
    )
    assert not list(tmp_path.glob(".argo-lint-staging-*"))


def test_a_rejected_lint_does_not_create_an_output_directory(tmp_path, monkeypatch, capsys):
    """A path that did not exist before a denied or rejected run must not exist
    after it: creating it is a change to the directory the gate promises to
    leave alone."""
    exe = _fake_argo(tmp_path, 1, body='echo "rejected"')
    out = tmp_path / "never" / "created"
    args = build_parser().parse_args([
        "render-argo", "--input", VALID_PLAN, "--output-dir", str(out),
        "--argo-lint", "--argo-bin", str(exe),
    ])
    with pytest.raises(SystemExit) as exc:
        cmd_render_argo(args)
    assert exc.value.code == 1
    assert not out.exists(), "the output directory was created for a rejected render"
    assert not (tmp_path / "never").exists()


def test_a_policy_denial_is_reported_as_itself_not_as_a_missing_linter(tmp_path, capsys):
    """Rendering runs before the CLI is resolved, so a denied plan reports its
    typed violations rather than being masked by an absent linter."""
    out = tmp_path / "out"
    args = build_parser().parse_args([
        "render-argo", "--input", "configs/mission_plans/demo_gpu_no_fallback.yaml",
        "--output-dir", str(out), "--argo-lint", "--argo-bin", "argo-nope-xyz",
    ])
    with pytest.raises(PolicyViolationError):
        cmd_render_argo(args)
    assert not out.exists()


def test_stale_yaml_in_the_destination_is_part_of_the_verdict(tmp_path, monkeypatch, capsys):
    """`lint: passed` describes the directory a caller applies, not just the
    files this render happened to produce.

    The repository's own smoke globs the whole output directory, so a broken
    workflow left from an earlier plan would be applied alongside a render that
    reported success.
    """
    out = tmp_path / "out"
    out.mkdir()
    (out / "left-over.yaml").write_text("apiVersion: argoproj.io/v1alpha1\nkind: Workflow\n", encoding="utf-8")

    # A linter that rejects only when the leftover is present in what it is given.
    exe = tmp_path / "argo"
    exe.write_text(
        "#!/bin/sh\n"
        'dir="$4"\n'
        'for a in "$@"; do dir="$a"; done\n'
        'if [ -f "$dir/left-over.yaml" ]; then echo "left-over.yaml is invalid"; exit 1; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)

    args = build_parser().parse_args([
        "render-argo", "--input", VALID_PLAN, "--output-dir", str(out),
        "--argo-lint", "--argo-bin", str(exe),
    ])
    with pytest.raises(SystemExit) as exc:
        cmd_render_argo(args)
    assert exc.value.code == 1
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "lint-failed"
    assert "left-over" in data["lint_output"]
    # And the leftover is not republished or removed by the gate.
    assert (out / "left-over.yaml").exists()
    assert sorted(p.name for p in out.glob("*.yaml")) == ["left-over.yaml"]


@pytest.mark.parametrize("code", [2, 126, 127, 3])
def test_a_return_code_that_is_not_a_verdict_is_unavailable(tmp_path, code):
    """Argo reports a lint result it judged with status 1. A wrapper that could
    not be run, or a runtime failure, says nothing about the manifests."""
    exe = _fake_argo(tmp_path, code)
    target = tmp_path / "m"
    target.mkdir()
    with pytest.raises(ArgoLintUnavailable, match="not a lint verdict"):
        argo_lint_path(target, argo_bin=str(exe))


def test_concurrent_publishes_do_not_interleave(tmp_path):
    """Two renders publishing into one directory must not leave a mixture.

    The critical section is held open deliberately: without the lock both
    threads enter it together and the recorded order shows it, which is the
    condition that lets their files interleave in the first place.
    """
    import threading
    import time

    from orbital_mission_compiler.cli import _publish, _publish_lock

    out = tmp_path / "out"
    order: list[str] = []
    barrier = threading.Barrier(2)

    def publish(tag: str) -> None:
        staging = tmp_path / f"stage-{tag}"
        staging.mkdir()
        for i in range(3):
            (staging / f"f{i}.yaml").write_text(f"{tag}\n", encoding="utf-8")
        barrier.wait()
        with _publish_lock(out):
            order.append(f"{tag}-start")
            time.sleep(0.2)
            _publish(sorted(staging.glob("*.yaml")), out)
            order.append(f"{tag}-end")

    threads = [threading.Thread(target=publish, args=(t,)) for t in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert order in (
        ["A-start", "A-end", "B-start", "B-end"],
        ["B-start", "B-end", "A-start", "A-end"],
    ), f"the critical sections overlapped: {order}"
    contents = {p.read_text(encoding="utf-8").strip() for p in out.glob("*.yaml")}
    assert len(contents) == 1, f"the directory holds a mixture: {contents}"


def test_the_gate_publishes_under_the_lock(tmp_path, capsys):
    """Holding the lock has to block the gate.

    The lock existing and the gate taking it are different claims: a test that
    calls the lock itself proves the primitive works, not that publishing goes
    through it.
    """
    import threading
    import time

    from orbital_mission_compiler.cli import _publish_lock

    out = tmp_path / "out"
    exe = _fake_argo(tmp_path, 0)
    args = build_parser().parse_args([
        "render-argo", "--input", VALID_PLAN, "--output-dir", str(out),
        "--argo-lint", "--argo-bin", str(exe),
    ])
    done = threading.Event()

    def run() -> None:
        try:
            cmd_render_argo(args)
        finally:
            done.set()

    with _publish_lock(out):
        worker = threading.Thread(target=run)
        worker.start()
        # Long enough for the render and the lint, which are not under the lock.
        time.sleep(1.0)
        published_while_held = sorted(p.name for p in out.glob("*.yaml")) if out.is_dir() else []
        assert not published_while_held, f"published while the lock was held: {published_while_held}"
        assert not done.is_set()
    worker.join(timeout=20)
    assert done.is_set(), "the gate never finished after the lock was released"
    assert list(out.glob("*.yaml")), "nothing was published after the lock was released"


def test_the_lint_gate_does_not_overwrite_another_missions_artifacts(tmp_path, capsys):
    """The gate stages into a fresh directory, so the writer's own overwrite
    preflight sees nothing to protect.

    Without the same check at the publish boundary, `--argo-lint` would be the
    one path that replaces another mission's output -- and two mission ids that
    sanitize alike render to the same filename, so it would do it silently.
    """
    exe = _fake_argo(tmp_path, 0)
    out = tmp_path / "shared"

    def plan(mission_id, name):
        p = tmp_path / name
        p.write_text(
            f"mission_id: {mission_id}\n"
            "events:\n"
            "  - timestamp: '2026-08-01T00:00:00Z'\n"
            "    event_type: acquisition\n"
            "    instrument: cam\n"
            "    duration_seconds: 60\n"
            "    services:\n"
            "      - service_id: svc\n"
            "        priority: 50\n"
            "        steps:\n"
            "          - {name: a, image: 'busybox:1.36'}\n",
            encoding="utf-8",
        )
        return p

    def render(plan_path):
        return build_parser().parse_args([
            "render-argo", "--input", str(plan_path), "--output-dir", str(out),
            "--argo-lint", "--argo-bin", str(exe),
        ])

    cmd_render_argo(render(plan("foo_bar", "one.yaml")))
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "ok"
    kept = {p.name: p.read_text(encoding="utf-8") for p in out.glob("*.yaml")}
    assert len(kept) == 1

    with pytest.raises(SystemExit) as exc:
        cmd_render_argo(render(plan("foo.bar", "two.yaml")))
    assert exc.value.code == 2
    data = json.loads(capsys.readouterr().out)
    assert data["reason"] == "not-owned", data
    assert {p.name: p.read_text(encoding="utf-8") for p in out.glob("*.yaml")} == kept

    # Re-rendering the same mission is still fine.
    cmd_render_argo(render(plan("foo_bar", "three.yaml")))
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


def test_a_failed_restore_keeps_the_only_remaining_copy(tmp_path, monkeypatch, capsys):
    """When publishing fails and putting a displaced file back also fails, the
    backup is the only copy of that file left.

    Deleting it on the way out of a failed rollback loses the previous good
    artifact for good, while the command reports the directory as restored.
    """
    out = tmp_path / "out"
    exe = _fake_argo(tmp_path, 0)

    def render_args(plan):
        return build_parser().parse_args([
            "render-argo", "--input", str(plan), "--output-dir", str(out),
            "--argo-lint", "--argo-bin", str(exe),
        ])

    cmd_render_argo(render_args(_multi_service_plan(tmp_path, ["a", "b"])))
    capsys.readouterr()
    previous = sorted(p.name for p in out.glob("*.yaml"))
    assert len(previous) == 2

    real_replace = os.replace
    published_count = {"n": 0}
    backup_marker = ".orbital-publish-backup-"

    def failing_replace(src, dst):
        # Keyed on the paths, not a call count: the writers publish through
        # os.replace as well, and staging lives inside the output directory, so
        # both counting and a substring test would fire during the render.
        if backup_marker in str(src):
            raise OSError(13, "Permission denied")  # a restore
        if Path(dst).parent == out:
            published_count["n"] += 1
            if published_count["n"] == 2:
                raise OSError(13, "Permission denied")  # the second file lands badly
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(SystemExit) as exc:
        cmd_render_argo(render_args(_multi_service_plan(tmp_path, ["a", "b"])))
    assert exc.value.code == 2
    data = json.loads(capsys.readouterr().out)
    monkeypatch.undo()

    assert data["reason"] == "rollback-incomplete", data
    assert data["output_modified"] is True
    assert data["unrestored"], data
    recovery = Path(data["recovery_directory"])
    assert recovery.is_dir(), "the recovery directory was deleted"
    survivors = sorted(p.name for p in recovery.glob("*.yaml"))
    assert survivors, "the only copy of the displaced file is gone"


def test_a_leftover_yml_is_part_of_the_verdict(tmp_path, capsys):
    """`kubectl apply -f <dir>` consumes .yml and .json too, so a gate that
    claims to lint what the directory will hold cannot look only at .yaml."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "left-over.yml").write_text("apiVersion: argoproj.io/v1alpha1\nkind: Workflow\n", encoding="utf-8")

    exe = tmp_path / "argo"
    exe.write_text(
        "#!/bin/sh\n"
        'dir=""\nfor a in "$@"; do dir="$a"; done\n'
        'if [ -f "$dir/left-over.yml" ]; then echo "left-over.yml is invalid"; exit 1; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)

    args = build_parser().parse_args([
        "render-argo", "--input", VALID_PLAN, "--output-dir", str(out),
        "--argo-lint", "--argo-bin", str(exe),
    ])
    with pytest.raises(SystemExit) as exc:
        cmd_render_argo(args)
    assert exc.value.code == 1
    assert "left-over" in json.loads(capsys.readouterr().out)["lint_output"]


def test_the_lock_is_the_same_for_aliased_output_paths(tmp_path):
    """`absolute()` leaves `..` in place and does not resolve links, so two
    spellings of one directory would take different locks and not exclude each
    other -- which is the case the lock exists for.

    Observed by holding one spelling and watching the other block, rather than
    by recomputing the key here, which would only restate the implementation.
    """
    import threading

    from orbital_mission_compiler.cli import _publish_lock

    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "sub").mkdir()
    aliases = [tmp_path / "link", tmp_path / "sub" / ".." / "real"]
    (tmp_path / "link").symlink_to(real)

    for alias in aliases:
        entered = threading.Event()
        release = threading.Event()

        def take_alias() -> None:
            with _publish_lock(alias):
                entered.set()
                release.wait(timeout=10)

        with _publish_lock(real):
            worker = threading.Thread(target=take_alias)
            worker.start()
            blocked = not entered.wait(timeout=1.0)
            assert blocked, f"{alias} did not share the lock with {real}"
        assert entered.wait(timeout=10), f"{alias} never acquired the lock after release"
        release.set()
        worker.join(timeout=10)
        assert not worker.is_alive()


def test_a_new_file_that_cannot_be_removed_is_an_incomplete_rollback(tmp_path, monkeypatch, capsys):
    """Rollback has two ways to leave the directory modified, and only one was
    reported.

    A file this render created has no displaced copy to restore, so failing to
    remove it left `unrestored` empty and the caller was told the output had
    been rolled back while the new artifact was still sitting in it.
    """
    out = tmp_path / "out"
    exe = _fake_argo(tmp_path, 0)
    args = build_parser().parse_args([
        "render-argo", "--input", str(_multi_service_plan(tmp_path, ["a", "b"])),
        "--output-dir", str(out), "--argo-lint", "--argo-bin", str(exe),
    ])

    real_replace = os.replace
    stuck: dict[str, Path] = {}

    def failing_replace(src, dst):
        target = Path(dst)
        if target.parent == out and stuck:
            raise OSError(28, "No space left on device")
        result = real_replace(src, dst)
        if target.parent == out:
            stuck["first"] = target
        return result

    real_unlink = Path.unlink

    def failing_unlink(self, *a, **kw):
        if stuck.get("first") == self:
            raise OSError(13, "Permission denied")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(os, "replace", failing_replace)
    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with pytest.raises(SystemExit) as exit_info:
        cmd_render_argo(args)
    assert exit_info.value.code == 2
    report = json.loads(capsys.readouterr().out)

    assert report["reason"] == "rollback-incomplete", report
    assert report["output_modified"] is True
    assert report["unremoved_published"] == [str(stuck["first"])], report
    assert "rolled back" not in report["message"]
    # The claim has to match the disk: the file really is still there.
    assert stuck["first"].exists()


def test_a_prune_that_stops_part_way_is_not_reported_as_a_failed_publish(tmp_path, monkeypatch, capsys):
    """Publication commits and drops its backup before pruning starts, so a
    prune that fails half-way cannot be rolled back.

    Reporting it as `publish-failed` and "rolled back to its previous contents"
    is wrong three times over: publication succeeded, the failing phase was the
    prune, and nothing was restored.
    """
    out = tmp_path / "out"
    exe = _fake_argo(tmp_path, 0)

    def render(service_ids, *extra):
        return build_parser().parse_args([
            "render-argo", "--input", str(_multi_service_plan(tmp_path, service_ids)),
            "--output-dir", str(out), "--argo-lint", "--argo-bin", str(exe), *extra,
        ])

    cmd_render_argo(render(["a", "b", "c"]))
    capsys.readouterr()
    assert len(list(out.glob("*.yaml"))) == 3

    doomed = sorted(p for p in out.glob("*.yaml") if "-a-" not in p.name)
    assert len(doomed) == 2
    real_unlink = Path.unlink

    def failing_unlink(self, *a, **kw):
        if self == doomed[-1]:
            raise OSError(13, "Permission denied")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with pytest.raises(SystemExit) as exit_info:
        cmd_render_argo(render(["a"], "--prune"))
    assert exit_info.value.code == 2
    report = json.loads(capsys.readouterr().out)

    assert report["reason"] == "prune-failed", report
    assert "rolled back" not in report["message"]
    assert report["pruned"] == [str(doomed[0])], report
    assert report["not_pruned"] == [str(doomed[-1])], report
    # The published manifest is in place, which is what makes "publish-failed"
    # the wrong word for this.
    assert report["files"] and all(Path(f).exists() for f in report["files"])
    assert not doomed[0].exists() and doomed[-1].exists()


def test_a_stale_artifact_that_fails_lint_does_not_block_its_own_prune(tmp_path, capsys):
    """`--prune` exists to remove artifacts a shrunk plan no longer produces.

    Carrying them into the lint candidate first lets an invalid one fail the
    gate, which stops the publish, which stops the prune -- so the one command
    that could repair the directory is the one the bad file disables.
    """
    out = tmp_path / "out"
    clean = _fake_argo(tmp_path, 0)

    def render(service_ids, exe, *extra):
        return build_parser().parse_args([
            "render-argo", "--input", str(_multi_service_plan(tmp_path, service_ids)),
            "--output-dir", str(out), "--argo-lint", "--argo-bin", str(exe), *extra,
        ])

    cmd_render_argo(render(["a", "b"], clean))
    capsys.readouterr()
    stale = next(p for p in out.glob("*.yaml") if "-b-" in p.name)

    # A linter that rejects whatever directory it is given if the stale file is
    # in it -- standing in for the file itself being invalid.
    picky = _fake_argo(
        tmp_path, 0, name="argo-picky",
        body=f'for a in "$@"; do\n'
             f'  if [ -d "$a" ] && [ -e "$a/{stale.name}" ]; then exit 1; fi\n'
             f'done',
    )
    cmd_render_argo(render(["a"], picky, "--prune"))
    report = json.loads(capsys.readouterr().out)

    assert report["status"] == "ok", report
    assert report["pruned"] == [str(stale)], report
    assert not stale.exists()
    assert len(list(out.glob("*.yaml"))) == 1


def test_every_command_that_prunes_reports_a_failed_prune_the_same_way(tmp_path, monkeypatch, capsys):
    """The gate is not the only caller that prunes.

    `render-argo` without the gate and `render-kueue` prune too, and a prune
    that stops part-way leaves them with the same problem to act on. Letting it
    surface as a traceback there loses what was removed and what was not, and
    breaks the one-JSON-document contract on the way out.
    """
    out = tmp_path / "out"

    def render(service_ids, *extra):
        return build_parser().parse_args([
            "render-argo", "--input", str(_multi_service_plan(tmp_path, service_ids)),
            "--output-dir", str(out), *extra,
        ])

    cmd_render_argo(render(["a", "b", "c"]))
    capsys.readouterr()
    doomed = sorted(p for p in out.glob("*.yaml") if "-a-" not in p.name)
    assert len(doomed) == 2

    real_unlink = Path.unlink

    def failing_unlink(self, *a, **kw):
        if self == doomed[-1]:
            raise OSError(13, "Permission denied")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with pytest.raises(SystemExit) as exit_info:
        cmd_render_argo(render(["a"], "--prune"))
    assert exit_info.value.code == 2

    captured = capsys.readouterr()
    report = json.loads(captured.out)  # one document, not a traceback
    assert report["reason"] == "prune-failed", report
    assert report["pruned"] == [str(doomed[0])]
    assert report["not_pruned"] == [str(doomed[-1])]
    assert report["output_modified"] is True
    assert "lint" not in report, "the ungated path never ran a linter"


@pytest.mark.skipif(not ARGO_AVAILABLE, reason="argo CLI not installed")
def test_a_file_the_linter_cannot_parse_is_not_a_pass(tmp_path, capsys):
    """`argo lint` logs a file it cannot parse and carries on, exiting 0 as long
    as anything else in the target lints.

    The gate always stages its own valid manifests alongside, so that condition
    always holds and the exit status alone says "these manifests are valid"
    about a set containing one the linter never read. `kubectl apply -f <dir>`
    would choke on it. Uses the real CLI, because the behaviour under test is
    the CLI's.
    """
    out = tmp_path / "out"
    out.mkdir()
    (out / "zz-unparseable.yaml").write_text(
        "apiVersion: argoproj.io/v1alpha1\nkind: Workflow\nmetadata:\n  name: [unclosed\n",
        encoding="utf-8",
    )
    args = build_parser().parse_args([
        "render-argo", "--input", str(_multi_service_plan(tmp_path, ["a"])),
        "--output-dir", str(out), "--argo-lint",
    ])

    with pytest.raises(SystemExit) as exit_info:
        cmd_render_argo(args)
    assert exit_info.value.code == 1, "an unreadable manifest in the set is a verdict, not a pass"
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "lint-failed", report
    assert "yaml file is not valid" in report["lint_output"]
    # Nothing was published: the directory holds only what was already there.
    assert sorted(p.name for p in out.glob("*.yaml")) == ["zz-unparseable.yaml"]


def test_the_lock_file_being_unopenable_is_a_structured_error(tmp_path, monkeypatch, capsys):
    """The lock lives at a derivable path in the shared temp directory and is
    created 0600 by whoever renders first, so a second user cannot open it. That
    is one more way the gate cannot run, not a traceback."""
    exe = _fake_argo(tmp_path, 0)
    args = build_parser().parse_args([
        "render-argo", "--input", str(_multi_service_plan(tmp_path, ["a"])),
        "--output-dir", str(tmp_path / "out"), "--argo-lint", "--argo-bin", str(exe),
    ])

    real_open = os.open

    def refuse_lock(path, *a, **kw):
        if "orbital-publish-" in str(path):
            raise PermissionError(13, "Permission denied")
        return real_open(path, *a, **kw)

    monkeypatch.setattr(os, "open", refuse_lock)
    with pytest.raises(SystemExit) as exit_info:
        cmd_render_argo(args)
    assert exit_info.value.code == 2
    report = json.loads(capsys.readouterr().out)  # one document, not a traceback
    assert report["reason"] == "publish-lock-unavailable", report
    assert not (tmp_path / "out").exists(), "a gate that could not run must not create the output"

# ── The lock is shared with the ungated writer ──────────────────────────


def _render_argo_args(plan: str, out: Path, lint: bool = False):
    parser = build_parser()
    argv = ["render-argo", "--input", plan, "--output-dir", str(out), "--policy-engine", "baseline"]
    if lint:
        argv.append("--argo-lint")
    return parser.parse_args(argv)


def test_plain_render_argo_takes_the_publish_lock(tmp_path, monkeypatch, capsys):
    """A gated run snapshots, lints, then publishes; an ungated one must not cut in.

    Without a shared lock the plain writer can replace files in the destination
    between the gate's snapshot and its publication, and the verdict then describes
    a directory that no longer exists.
    """
    import contextlib

    from orbital_mission_compiler import cli

    taken: list[str] = []

    @contextlib.contextmanager
    def _record(out_dir):
        taken.append(os.path.realpath(out_dir))
        yield

    monkeypatch.setattr(cli, "_publish_lock", _record)
    out = tmp_path / "out"
    cmd_render_argo(_render_argo_args(VALID_PLAN, out))
    capsys.readouterr()

    assert taken == [os.path.realpath(out)]


def test_plain_render_argo_still_renders_where_the_lock_cannot_be_taken(tmp_path, monkeypatch, capsys):
    """The gate exits 2 without the lock; the plain writer has no verdict to protect.

    A platform with no flock cannot run the gate at all, so there is no gated writer
    to interleave with, and refusing to render would be a new failure for a command
    that never promised exclusivity.
    """
    import contextlib

    from orbital_mission_compiler import cli

    @contextlib.contextmanager
    def _unavailable(out_dir):
        raise cli.PublishLockUnavailable("no flock here")
        yield  # pragma: no cover - unreachable, keeps this a generator

    monkeypatch.setattr(cli, "_publish_lock", _unavailable)
    out = tmp_path / "out"
    cmd_render_argo(_render_argo_args(VALID_PLAN, out))
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "ok"
    assert payload["files"]
    assert list(out.glob("*.yaml"))
