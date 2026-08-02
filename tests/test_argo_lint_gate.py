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
import yaml

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
    survivor.write_text(
        "apiVersion: argoproj.io/v1alpha1\nkind: Workflow\nmetadata:\n  name: previous-good\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc:
        cmd_render_argo(args)
    assert exc.value.code == 1
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "lint-failed"
    assert data["files"] == []
    assert "template undefined" in data["lint_output"]
    # Nothing new landed, and the render that did pass is still there.
    assert [p.name for p in out.glob("*.yaml")] == ["previous-good.yaml"]
    assert "name: previous-good" in survivor.read_text(encoding="utf-8")
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
    # Our diagnostic, not Argo's log line. The file is rejected before the CLI is
    # invoked at all, so a reworded Argo message cannot turn this into a pass.
    assert "zz-unparseable.yaml" in report["lint_output"]
    assert "cannot be parsed" in report["lint_output"]
    # Nothing was published: the directory holds only what was already there.
    assert sorted(p.name for p in out.glob("*.yaml")) == ["zz-unparseable.yaml"]


def test_the_lock_file_being_unopenable_is_a_structured_error(tmp_path, monkeypatch, capsys):
    """The lock lives at a derivable path in the shared temp directory, so a second
    user can be refused on it -- by a mode another user set, by a directory they
    cannot traverse, or by anything else the OS decides. That is one more way the
    gate cannot run, and it reports as a structured error rather than a traceback.

    The gate creates the file 0666 for exactly this reason; a permission refusal is
    still possible and is what this covers, not the mode the gate itself chooses."""
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
    def _record(out_dir, *args):
        taken.append(os.path.realpath(out_dir))
        yield

    monkeypatch.setattr(cli, "_publish_lock", _record)
    out = tmp_path / "out"
    cmd_render_argo(_render_argo_args(VALID_PLAN, out))
    capsys.readouterr()

    assert taken == [os.path.realpath(out)]


def test_plain_render_argo_renders_where_no_process_can_lock(tmp_path, monkeypatch, capsys):
    """A platform with no flock has no gated writer to interleave with.

    Nothing can take the lock there, so nothing is holding the directory, and
    refusing to render would be a new failure for a command that never promised
    exclusivity of its own.
    """
    import contextlib

    from orbital_mission_compiler import cli

    @contextlib.contextmanager
    def _unsupported(out_dir, *args):
        raise cli.PublishLockUnsupported("no flock here")
        yield  # pragma: no cover - unreachable, keeps this a generator

    monkeypatch.setattr(cli, "_publish_lock", _unsupported)
    out = tmp_path / "out"
    cmd_render_argo(_render_argo_args(VALID_PLAN, out))
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "ok"
    assert payload["files"]
    assert list(out.glob("*.yaml"))


def test_plain_render_argo_refuses_when_the_lock_exists_and_will_not_open(tmp_path, monkeypatch, capsys):
    """A lock it cannot open is one somebody else is holding.

    That is the case the lock was added for: a gated run created it, is holding it,
    and is about to publish into this directory. Writing anyway would replace the
    files between its snapshot and its publication, so the verdict it reports would
    describe a directory that no longer exists. An earlier revision caught the same
    exception for both causes and carried on, which failed open exactly here.
    """
    import contextlib

    from orbital_mission_compiler import cli

    @contextlib.contextmanager
    def _held(out_dir, *args):
        raise cli.PublishLockUnavailable("another user holds the lock file")
        yield  # pragma: no cover - unreachable, keeps this a generator

    monkeypatch.setattr(cli, "_publish_lock", _held)
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as excinfo:
        cmd_render_argo(_render_argo_args(VALID_PLAN, out))
    assert excinfo.value.code == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["reason"] == "publish-lock-unavailable"
    assert not out.exists() or not list(out.glob("*.yaml"))


def test_the_unsupported_case_is_a_kind_of_unavailable(tmp_path):
    """The gate needs exclusivity for either cause, so it still catches both."""
    from orbital_mission_compiler import cli

    assert issubclass(cli.PublishLockUnsupported, cli.PublishLockUnavailable)


def test_a_platform_without_fcntl_reports_the_unsupported_kind(tmp_path, monkeypatch):
    """Which exception the fcntl branch raises is what makes the two cases differ.

    The tests either side of this one substitute the lock, so neither reaches the
    raise itself: raising the parent here would make a platform that simply cannot
    lock refuse to render, and nothing would have noticed.
    """
    import builtins

    from orbital_mission_compiler import cli

    real_import = builtins.__import__

    def _no_fcntl(name, *rest):
        if name == "fcntl":
            raise ImportError("no fcntl on this platform")
        return real_import(name, *rest)

    monkeypatch.setattr(builtins, "__import__", _no_fcntl)
    with pytest.raises(cli.PublishLockUnsupported):
        with cli._publish_lock(tmp_path / "out"):
            pass  # pragma: no cover - the lock never opens


def test_an_unopenable_lock_reports_the_plain_unavailable_kind(tmp_path):
    """A lock file this process cannot open is one another process is holding."""
    import os

    from orbital_mission_compiler import cli

    out = tmp_path / "out"
    lock = cli.publish_lock_path(out)
    lock.write_text("")
    os.chmod(lock, 0o000)
    try:
        if os.access(lock, os.R_OK):  # running as root; the mode means nothing
            pytest.skip("cannot make a file unopenable as this user")
        with pytest.raises(cli.PublishLockUnavailable) as excinfo:
            with cli._publish_lock(out):
                pass  # pragma: no cover - the lock never opens
        assert not isinstance(excinfo.value, cli.PublishLockUnsupported)
    finally:
        os.chmod(lock, 0o600)
        lock.unlink()

# ── The lock has to be takeable by the next user, not just the first ────


def _lock_path_for(out: Path) -> Path:
    """Asked of the code rather than recomputed, so it cannot drift from it."""
    from orbital_mission_compiler import cli

    return cli.publish_lock_path(out)


@pytest.mark.parametrize("umask", [0o022, 0o077])
def test_the_lock_file_stays_openable_by_another_user(tmp_path, umask):
    """The file outlives the run, so its mode decides who may render next.

    flock is released when the descriptor closes, so a lock file left behind says
    nothing about a holder. Created 0600 it locked every other user out for good,
    and the mode argument to open() is masked by the umask, so asking for 0666 is
    not enough on its own.
    """
    import os
    import stat

    from orbital_mission_compiler import cli

    out = tmp_path / "out"
    lock = _lock_path_for(out)
    if lock.exists():
        lock.unlink()

    previous = os.umask(umask)
    try:
        with cli._publish_lock(out):
            pass
        mode = stat.S_IMODE(lock.stat().st_mode)
        assert mode == 0o666, f"umask {oct(umask)} left the lock at {oct(mode)}"
        # Taking it a second time has to work on the file that is already there.
        with cli._publish_lock(out):
            pass
    finally:
        os.umask(previous)
        if lock.exists():
            lock.unlink()


def test_a_symlink_at_the_lock_path_is_refused(tmp_path):
    """The path is predictable and shared, and the mode is now permissive.

    0600 was standing in for this: the open must refuse a symlink somebody planted
    rather than follow it into a file that is none of its business.
    """
    from orbital_mission_compiler import cli

    out = tmp_path / "out"
    lock = _lock_path_for(out)
    if lock.exists():
        lock.unlink()
    victim = tmp_path / "victim"
    victim.write_text("untouched")
    lock.symlink_to(victim)
    try:
        with pytest.raises(cli.PublishLockUnavailable):
            with cli._publish_lock(out):
                pass  # pragma: no cover - the lock never opens
        assert victim.read_text() == "untouched"
    finally:
        lock.unlink()


def test_a_held_lock_times_out_instead_of_waiting_forever(tmp_path, capsys):
    """Waiting for exclusivity has an upper bound, and giving up is not a verdict.

    flock(LOCK_EX) with no LOCK_NB waits indefinitely. The lock path is derived
    from the output directory and lives in the shared temp directory, so a holder
    that hung -- or any local user who can open that file -- turned this command
    into an unbounded stall. Giving up has to report the gate could not run, never
    that the linter rejected something: the linter never saw it.
    """
    from orbital_mission_compiler import cli

    out = tmp_path / "out"
    out.mkdir()
    exe = _fake_argo(tmp_path, 0)
    args = build_parser().parse_args([
        "render-argo", "--input", VALID_PLAN, "--output-dir", str(out),
        "--argo-lint", "--argo-bin", str(exe), "--lock-timeout", "0.3",
    ])
    # A second descriptor on the same file, held for the duration of the call.
    with cli._publish_lock(out):
        with pytest.raises(SystemExit) as exc:
            cmd_render_argo(args)
    assert exc.value.code == 2, "a lock we could not take is 'could not run', not a rejection"
    data = json.loads(capsys.readouterr().out)
    # "not-run" is this path's vocabulary; "unavailable" is the missing-CLI one.
    assert data["lint"] == "not-run" and data["reason"] == "publish-lock-unavailable", data
    assert not list(out.glob("*.yaml")), "nothing may be published without the lock"


def test_render_kueue_takes_the_same_lock_as_render_argo(tmp_path, monkeypatch, capsys):
    """Every writer of the output root, not only the Argo ones.

    The gate's claim is that what was linted is what was published. render-kueue
    writes the same caller-selected directory, so while it took no lock it could
    replace files between the gate's snapshot and its publish -- and the verdict
    would then describe a directory that no longer existed. A lock only some of a
    directory's writers take is not a lock on the directory.
    """
    import contextlib

    from orbital_mission_compiler import cli
    from orbital_mission_compiler.cli import cmd_render_kueue

    taken: list[str] = []

    @contextlib.contextmanager
    def _record(out_dir, *args):
        taken.append(os.path.realpath(out_dir))
        yield

    monkeypatch.setattr(cli, "_publish_lock", _record)
    out = tmp_path / "out"
    args = build_parser().parse_args([
        "render-kueue", "--input", VALID_PLAN, "--output-dir", str(out),
        "--policy-engine", "baseline",
    ])
    cmd_render_kueue(args)
    capsys.readouterr()
    assert taken == [os.path.realpath(out)]


@pytest.mark.parametrize(
    "body,expected",
    [
        ("apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: [unclosed\n", "cannot be parsed"),
        ("- just\n- a\n- list\n", "not an object"),
        ("kind: Workflow\n", "has no apiVersion"),
    ],
    ids=["unparseable", "not-a-mapping", "missing-fields"],
)
def test_a_document_kubectl_would_reject_fails_the_gate_before_argo_runs(
    tmp_path, capsys, body, expected
):
    """Syntax is decided here, not read out of Argo's log.

    Argo logs a file it cannot parse and exits 0 as long as something else in the
    target lints -- which is always, because the gate stages its own manifests
    alongside. The compensation for that was matching the literal string
    `msg="yaml file is not valid"` in its output, which a reworded release, a
    locale or a log-format change would silently turn back into a pass.

    So every staged document is read here first, with the CLI never invoked: it
    must parse, be a mapping, and carry the fields that make it a Kubernetes
    object. Duplicate keys are refused too, because yaml.safe_load keeps the last
    of the pair and the loss is invisible in the result.
    """
    out = tmp_path / "out"
    out.mkdir()
    (out / "zz-bad.yaml").write_text(body, encoding="utf-8")
    # A CLI that would PASS anything, so a failure here can only come from the
    # local check.
    exe = _fake_argo(tmp_path, 0)
    args = build_parser().parse_args([
        "render-argo", "--input", str(_multi_service_plan(tmp_path, ["a"])),
        "--output-dir", str(out), "--argo-lint", "--argo-bin", str(exe),
    ])

    with pytest.raises(SystemExit) as exit_info:
        cmd_render_argo(args)
    assert exit_info.value.code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "lint-failed", report
    assert expected in report["lint_output"], report["lint_output"]
    assert not (tmp_path / "argv.txt").exists(), "the CLI must not have been consulted"
    assert [p.name for p in out.glob("*.yaml")] == ["zz-bad.yaml"], "nothing was published"


@pytest.mark.parametrize("fail_on", [1, 2], ids=["second-file", "third-file"])
def test_render_kueue_leaves_one_generation_or_the_other(tmp_path, monkeypatch, capsys, fail_on):
    """A failure part-way through publication is not allowed to mix the two.

    Each file was written atomically on its own, but the set is what a caller
    deploys. A failure on the Nth left the directory holding some manifests from
    this render and some from the last, and nothing said so -- and for this
    command the set is a Job beside the priority classes it references, so a mixed
    directory is a Job naming values that have moved.

    The injected failure is on os.replace, which is the step that publishes.
    """
    import os as _os

    from orbital_mission_compiler import cli
    from orbital_mission_compiler.cli import cmd_render_kueue

    out = tmp_path / "out"
    out.mkdir()
    plan = _multi_service_plan(tmp_path, ["a", "b", "c"])

    def _args():
        return build_parser().parse_args([
            "render-kueue", "--input", str(plan), "--output-dir", str(out),
            "--emit-priority-classes", "--policy-engine", "baseline",
        ])

    cmd_render_kueue(_args())
    capsys.readouterr()
    before = {p.name: p.read_text(encoding="utf-8") for p in sorted(out.glob("*.yaml"))}
    assert len(before) > fail_on, "need more files than the injected failure point"

    real_replace = _os.replace
    calls = {"n": 0, "fired": False}

    def flaky(src, dst, *a, **kw):
        # Only the publishing replaces are counted. atomic_write uses os.replace
        # as well, and the staging directory lives inside the output directory, so
        # a prefix test would also catch the staging writes and fail the render
        # before it ever reached the step under test.
        #
        # And it fires exactly once. Rollback republishes through the same call,
        # so a wrapper that kept failing would break the restore too and this would
        # be measuring a disk that never recovers rather than a single write that
        # failed -- which is the case the rollback exists for.
        if Path(dst).parent == out and not Path(dst).name.startswith("."):
            calls["n"] += 1
            if calls["n"] > fail_on and not calls["fired"]:
                calls["fired"] = True
                raise OSError(28, "No space left on device")
        return real_replace(src, dst, *a, **kw)

    monkeypatch.setattr(cli.os, "replace", flaky)
    with pytest.raises(SystemExit) as exc:
        cmd_render_kueue(_args())
    assert exc.value.code == 2
    capsys.readouterr()
    monkeypatch.undo()

    after = {p.name: p.read_text(encoding="utf-8") for p in sorted(out.glob("*.yaml"))}
    assert after == before, (
        "the directory must hold exactly the previous generation after a failed "
        f"publish, got {sorted(set(after) ^ set(before))} differing"
    )


def test_tab_indented_json_is_read_the_way_kubectl_reads_it(tmp_path):
    """PyYAML is YAML 1.1 and refuses a tab as indentation; kubectl does not.

    A file beginning with `{` goes to kubectl's JSON decoder, where tabs are
    ordinary whitespace -- and `json.MarshalIndent(v, "", "\t")`, the Go default,
    produces exactly that. Reading it with the YAML parser called it malformed,
    which is the same false verdict the duplicate-key rule was removed for, and
    worse: the gate carries files in from the output directory on every run, so one
    such file would have failed every future render permanently.
    """
    import json as _json

    from orbital_mission_compiler.cli import _unreadable_documents

    d = tmp_path / "staging"
    d.mkdir()
    (d / "operator-config.json").write_text(
        _json.dumps(
            {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "t"}}, indent="\t"
        ),
        encoding="utf-8",
    )
    assert _unreadable_documents(d) == []


def test_a_parser_that_cannot_cope_is_not_a_lint_verdict(tmp_path):
    """A crash must not read as "the linter rejected this".

    PyYAML composes recursively, so deep nesting overflows the stack. The
    RecursionError escaped as a bare traceback with exit 1 -- and 1 is this gate's
    code for a lint failure, so CI would have recorded a crash as a rejected
    manifest. It is a gate that could not run: exit 2, no verdict.
    """
    from orbital_mission_compiler.cli import _unreadable_documents
    from orbital_mission_compiler.compiler import ArgoLintUnavailable

    d = tmp_path / "staging"
    d.mkdir()
    (d / "deep.yaml").write_text("[" * 6000 + "]" * 6000, encoding="utf-8")
    with pytest.raises(ArgoLintUnavailable, match="nests too deeply"):
        _unreadable_documents(d)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "-1", "abc"], ids=repr)
def test_a_lock_timeout_that_is_not_a_bound_is_refused(value):
    """The flag existed to impose a bound and could be used to remove one.

    argparse's `float` accepts nan and inf. With nan every comparison against the
    deadline is False so the wait never ends, and `min(0.2, max(0.0, nan))` is 0.0
    so it never sleeps either -- an unbounded busy-spin, worse than the blocking
    LOCK_EX it replaced, which at least waited in the kernel.
    """
    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "render-kueue", "--input", VALID_PLAN, "--output-dir", "/tmp/x",
            "--lock-timeout", value,
        ])


def test_render_kueue_prunes_under_the_lock_it_published_under(tmp_path, monkeypatch, capsys):
    """The window between publishing and pruning was outside the lock.

    The gate's own note says why that is not allowed: pruning outside it lets two
    renders of the same mission delete each other's newly published files. This
    command released the lock after publishing and pruned afterwards, so a gated
    render could pass its lint, publish, and have its files deleted by this one --
    with both reporting success.
    """
    import contextlib

    from orbital_mission_compiler import cli
    from orbital_mission_compiler.cli import cmd_render_kueue

    held_during: list[str] = []

    @contextlib.contextmanager
    def _watch(out_dir, *args):
        held_during.append("enter")
        yield
        held_during.append("exit")

    real_report = cli._report_stale

    def _note(*a, **kw):
        held_during.append("prune")
        return real_report(*a, **kw)

    monkeypatch.setattr(cli, "_publish_lock", _watch)
    monkeypatch.setattr(cli, "_report_stale", _note)
    args = build_parser().parse_args([
        "render-kueue", "--input", VALID_PLAN, "--output-dir", str(tmp_path / "out"),
        "--prune", "--policy-engine", "baseline",
    ])
    cmd_render_kueue(args)
    capsys.readouterr()
    assert held_during == ["enter", "prune", "exit"], held_during


def test_prune_does_not_reach_across_renderers(tmp_path, capsys):
    """One mission's Argo Workflow and Kueue Job are equally "ours".

    Both carry the same managed-by label and the same mission fingerprint, and
    stale detection scoped on exactly those two -- so `render-kueue --prune` into a
    directory an Argo render had published deleted the Workflow. With the gate that
    included a Workflow it had just linted and reported as published, which is the
    guarantee this branch exists to make.
    """
    from orbital_mission_compiler.cli import cmd_render_argo, cmd_render_kueue

    out = tmp_path / "out"
    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", VALID_PLAN, "--output-dir", str(out),
        "--policy-engine", "baseline",
    ]))
    capsys.readouterr()
    argo_files = {p.name for p in out.glob("*.yaml")}
    assert argo_files

    cmd_render_kueue(build_parser().parse_args([
        "render-kueue", "--input", VALID_PLAN, "--output-dir", str(out),
        "--prune", "--policy-engine", "baseline",
    ]))
    report = json.loads(capsys.readouterr().out)
    survived = {p.name for p in out.glob("*.yaml")}
    assert argo_files <= survived, (
        f"render-kueue --prune removed another renderer's output: "
        f"{sorted(argo_files - survived)}"
    )
    assert not report.get("pruned"), report.get("pruned")
    # Nor reported as stale: it is not stale, it is that renderer's live output,
    # and calling it stale would send an operator to delete a current artifact.
    assert not report.get("stale"), report.get("stale")


def test_prune_still_removes_this_renderers_own_previous_generation(tmp_path, capsys):
    """Scoping by renderer must not turn --prune into a no-op."""
    from orbital_mission_compiler.cli import cmd_render_kueue

    out = tmp_path / "out"
    args = build_parser().parse_args([
        "render-kueue", "--input", VALID_PLAN, "--output-dir", str(out),
        "--prune", "--policy-engine", "baseline",
    ])
    cmd_render_kueue(args)
    capsys.readouterr()
    produced = next(p for p in out.glob("*-kueue.yaml"))
    stale = out / "an-earlier-generation-kueue.yaml"
    produced.rename(stale)

    cmd_render_kueue(args)
    report = json.loads(capsys.readouterr().out)
    assert [Path(p).name for p in report.get("pruned", [])] == [stale.name], report
    assert not stale.exists()


@pytest.mark.parametrize("first,second", [("argo", "kueue"), ("kueue", "argo")], ids=str)
def test_prune_does_not_reach_across_renderers_either_way(tmp_path, capsys, first, second):
    """Both directions, because the first fix only closed one.

    Scoping on "every kind in the file is one this renderer can write" looked
    right and was not: both renderers emit ResourceClaimTemplate, so the
    standalone `-scheduler-fallback.yaml` is a subset of both sets and whichever
    command ran last deleted the other's. Measured: render-kueue kept the Argo
    Workflow, and render-argo then deleted the Kueue scheduler-fallback file.

    Attribution now rests on a kind only one renderer emits -- Workflow on one
    side, Job and WorkloadPriorityClass on the other -- and a file carrying
    neither is reported and never deleted.
    """
    from orbital_mission_compiler.cli import cmd_render_argo, cmd_render_kueue

    run = {"argo": cmd_render_argo, "kueue": cmd_render_kueue}
    out = tmp_path / "out"

    def _args(which, *extra):
        return build_parser().parse_args([
            f"render-{which}", "--input", "configs/mission_plans/sample_gpu_cpu_fallback.yaml",
            "--output-dir", str(out), "--dra-fallback", "--namespace", "default",
            "--policy-engine", "baseline", *extra,
        ])

    run[first](_args(first))
    capsys.readouterr()
    before = {p.name for p in out.glob("*.yaml")}
    assert before

    run[second](_args(second, "--prune"))
    capsys.readouterr()
    after = {p.name for p in out.glob("*.yaml")}
    assert before <= after, (
        f"render-{second} --prune removed render-{first}'s output: {sorted(before - after)}"
    )


def test_an_artifact_neither_renderer_claims_is_reported_not_deleted(tmp_path, capsys):
    """The standalone claim template carries no exclusive kind.

    Silently leaving it would be the leftover the stale report exists to prevent,
    and deleting it on a guess is how the cross-renderer loss happened. It is named
    under its own key and left alone.
    """
    from orbital_mission_compiler.cli import cmd_render_argo, cmd_render_kueue

    out = tmp_path / "out"
    cmd_render_kueue(build_parser().parse_args([
        "render-kueue", "--input", "configs/mission_plans/sample_gpu_cpu_fallback.yaml",
        "--output-dir", str(out), "--dra-fallback", "--namespace", "default",
        "--policy-engine", "baseline",
    ]))
    capsys.readouterr()
    fallback = next(p for p in out.glob("*-scheduler-fallback.yaml"))

    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", "configs/mission_plans/sample_gpu_cpu_fallback.yaml",
        "--output-dir", str(out), "--namespace", "default",
        "--policy-engine", "baseline", "--prune",
    ]))
    report = json.loads(capsys.readouterr().out)
    assert fallback.exists(), "an unattributable artifact must not be deleted"
    assert fallback.name in " ".join(report.get("stale_not_ours", [])), report


@pytest.mark.parametrize(
    "name,body,expect_reject",
    [
        ("tabbed.yaml", '{\n\t"apiVersion": "v1",\n\t"kind": "ConfigMap",\n\t"metadata": {"name": "a"}\n}\n', False),
        ("yaml.json", "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: b\n", False),
        ("bom.json", "\ufeff{\"apiVersion\":\"v1\",\"kind\":\"ConfigMap\",\"metadata\":{\"name\":\"c\"}}", False),
        ("leadws.json", '   \n  {"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"d"}}\n', False),
        ("arr.json", '[{"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"e"}}]', True),
        ("empty.json", "", False),
    ],
    ids=["tab-json-in-yaml-file", "yaml-in-json-file", "bom", "leading-whitespace",
         "top-level-array", "empty"],
)
def test_documents_are_read_the_way_kubectl_reads_them(tmp_path, name, body, expect_reject):
    """Each expectation here was taken from kubectl, not decided here.

    `kubectl apply --dry-run=client --validate=strict` was run on these exact
    bytes: it accepts tab-indented JSON in a .yaml file, YAML in a .json file, a
    UTF-8 BOM, and whitespace before the opening brace; it rejects a top-level
    array. An empty file is accepted as a document -- kubectl only objects when
    the WHOLE set is empty ("no objects passed to apply"), which is a property of
    the set and not of the file, and a render always contributes real manifests.

    An earlier version dispatched on the file extension. kubectl dispatches on
    content: NewYAMLOrJSONDecoder calls hasJSONPrefix, which skips leading
    whitespace and asks whether the first byte is `{`. Extension-based dispatch
    rejected two files that deploy, which is the same class of false verdict this
    function has now been corrected for twice.
    """
    from orbital_mission_compiler.cli import _unreadable_documents

    d = tmp_path / "staging"
    d.mkdir()
    (d / name).write_text(body, encoding="utf-8")
    problems = _unreadable_documents(d)
    assert bool(problems) is expect_reject, problems


def _plan_that_renders_nothing(tmp_path: Path, source: str = VALID_PLAN) -> Path:
    """The same mission, in a revision that legitimately produces no workload.

    Reached by turning every event into a download with no services. Emptying an
    acquisition event's services instead is refused by policy rule 3, and dropping
    the events is refused by rule 2, so this is the one shape that is schema-valid,
    policy-clean and renders nothing.
    """
    plan = yaml.safe_load(Path(source).read_text(encoding="utf-8"))
    for event in plan["events"]:
        event["event_type"] = "download"
        event["services"] = []
        event["ground_visibility"] = True
        event.setdefault("duration_seconds", 30.0)
        event.pop("instrument", None)
    out = tmp_path / "renders-nothing.yaml"
    out.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    return out


def test_prune_retires_the_last_artifact_when_the_plan_asks_for_none(tmp_path, capsys):
    """An empty desired set is a state to reconcile, not an absence of scope.

    The render before this one owned a Workflow. This revision of the same mission
    owns nothing, so --prune has to retire it: what stays behind is deployable, and
    `kubectl apply -f <dir>` would put back exactly the workload the plan dropped.
    """
    out = tmp_path / "out"
    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", VALID_PLAN, "--output-dir", str(out),
        "--prune", "--policy-engine", "baseline",
    ]))
    capsys.readouterr()
    previous = sorted(p.name for p in out.glob("*.yaml"))
    assert previous, "the first render produced nothing to retire"

    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", str(_plan_that_renders_nothing(tmp_path)),
        "--output-dir", str(out), "--prune", "--policy-engine", "baseline",
    ]))
    report = json.loads(capsys.readouterr().out)

    assert report["files"] == [], report
    assert sorted(Path(p).name for p in report.get("pruned", [])) == previous, report
    assert sorted(p.name for p in out.glob("*.yaml")) == [], sorted(out.iterdir())


def test_gated_prune_retires_the_last_artifact_when_the_plan_asks_for_none(tmp_path, capsys):
    """Nothing to lint is not a reason to leave the previous generation deployed.

    The gate exits before it reaches the lock, so today the artifact the plan no
    longer asks for survives a run that was asked to prune it.
    """
    out = tmp_path / "out"
    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", VALID_PLAN, "--output-dir", str(out),
        "--prune", "--policy-engine", "baseline",
    ]))
    capsys.readouterr()
    previous = sorted(p.name for p in out.glob("*.yaml"))
    assert previous

    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", str(_plan_that_renders_nothing(tmp_path)),
        "--output-dir", str(out), "--argo-lint", "--prune",
        "--policy-engine", "baseline",
    ]))
    report = json.loads(capsys.readouterr().out)

    assert report["status"] == "ok", report
    assert report["lint"] == "not-applicable", report
    assert sorted(Path(p).name for p in report.get("pruned", [])) == previous, report
    assert sorted(p.name for p in out.glob("*.yaml")) == []


def test_prune_retires_the_priority_class_bundle_once_emission_stops(tmp_path, capsys):
    """The bundle is cluster-scoped, which is not the same as unowned.

    It carries no mission fingerprint, so mission-scoped stale detection cannot see
    it, and turning --emit-priority-classes off leaves the classes on disk for the
    next `kubectl apply` to reinstate.
    """
    from orbital_mission_compiler.cli import cmd_render_kueue

    out = tmp_path / "out"
    base = [
        "render-kueue", "--input", VALID_PLAN, "--output-dir", str(out),
        "--priority-class", "--prune", "--policy-engine", "baseline",
    ]
    cmd_render_kueue(build_parser().parse_args(base + ["--emit-priority-classes"]))
    capsys.readouterr()
    bundle = out / "workload-priority-classes.yaml"
    assert bundle.exists(), sorted(out.iterdir())

    cmd_render_kueue(build_parser().parse_args(base))
    report = json.loads(capsys.readouterr().out)

    assert bundle.name in [Path(p).name for p in report.get("pruned", [])], report
    assert not bundle.exists(), sorted(out.iterdir())


OTHER_PLAN = "configs/mission_plans/sample_gpu_cpu_fallback.yaml"


def test_an_empty_render_prunes_only_its_own_mission(tmp_path, capsys):
    """The declared scope is what keeps an empty desired set from sweeping.

    Deriving the scope from the input rather than from what was written is what
    makes a render-nothing revision able to reconcile at all. The same change is
    what could let it reconcile far too much: with no scope, or the wrong one, a
    directory shared with another mission is a directory it would empty.
    """
    out = tmp_path / "shared"
    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", OTHER_PLAN, "--output-dir", str(out),
        "--policy-engine", "baseline",
    ]))
    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", VALID_PLAN, "--output-dir", str(out),
        "--policy-engine", "baseline",
    ]))
    capsys.readouterr()
    before = sorted(p.name for p in out.glob("*.yaml"))
    others = [n for n in before if "mission-alpha" not in n]
    assert others, before

    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", str(_plan_that_renders_nothing(tmp_path)),
        "--output-dir", str(out), "--prune", "--policy-engine", "baseline",
    ]))
    report = json.loads(capsys.readouterr().out)

    pruned = [Path(p).name for p in report.get("pruned", [])]
    # Both halves. An empty prune satisfies "nothing of another mission's went"
    # without reconciling anything, which is the bug this whole change is about.
    assert pruned, report
    assert all("mission-alpha" in n for n in pruned), pruned
    remaining = sorted(p.name for p in out.glob("*.yaml"))
    for name in others:
        assert name in remaining, f"{name} belongs to another mission and was pruned"


def test_an_empty_render_leaves_the_other_renderers_output_alone(tmp_path, capsys):
    """An empty desired set is still only this renderer's desired set."""
    from orbital_mission_compiler.cli import cmd_render_kueue

    out = tmp_path / "shared"
    cmd_render_kueue(build_parser().parse_args([
        "render-kueue", "--input", VALID_PLAN, "--output-dir", str(out),
        "--policy-engine", "baseline",
    ]))
    capsys.readouterr()
    kueue_files = sorted(p.name for p in out.glob("*.yaml"))
    assert kueue_files

    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", str(_plan_that_renders_nothing(tmp_path)),
        "--output-dir", str(out), "--prune", "--policy-engine", "baseline",
    ]))
    report = json.loads(capsys.readouterr().out)

    assert not report.get("pruned"), report
    assert sorted(p.name for p in out.glob("*.yaml")) == kueue_files


def test_claiming_the_bundle_does_not_let_kueue_prune_a_workflow(tmp_path, capsys):
    """Claiming artifacts without a mission must not widen the renderer scope.

    render-kueue now takes cluster-scoped artifacts into its stale scope so the
    priority-class bundle can be retired. Attribution by exclusive kind is what
    still has to keep it away from an Argo Workflow standing in the same
    directory, whether or not that Workflow carries a mission.
    """
    from orbital_mission_compiler.cli import cmd_render_kueue

    out = tmp_path / "shared"
    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", OTHER_PLAN, "--output-dir", str(out),
        "--policy-engine", "baseline",
    ]))
    capsys.readouterr()
    workflows = sorted(p.name for p in out.glob("*.yaml"))
    assert workflows

    cmd_render_kueue(build_parser().parse_args([
        "render-kueue", "--input", VALID_PLAN, "--output-dir", str(out),
        "--priority-class", "--prune", "--policy-engine", "baseline",
    ]))
    report = json.loads(capsys.readouterr().out)

    assert not report.get("pruned"), report
    for name in workflows:
        assert (out / name).exists(), f"{name} is the other renderer's and was pruned"


def test_the_lock_wait_outlasts_the_lint_it_is_held_across():
    """Two constants in two modules that have to stay in step.

    The gate takes the publish lock before it reads the destination and holds it
    through `argo lint`. A default wait shorter than the linter's own budget makes
    a second healthy writer give up while the first is still inside its allowance,
    so contention reads as a failure on the defaults alone.
    """
    from orbital_mission_compiler.cli import _DEFAULT_LOCK_TIMEOUT
    from orbital_mission_compiler.compiler import ARGO_LINT_TIMEOUT_SECONDS

    assert _DEFAULT_LOCK_TIMEOUT >= ARGO_LINT_TIMEOUT_SECONDS, (
        f"a writer waits {_DEFAULT_LOCK_TIMEOUT}s for a lock held across a lint "
        f"allowed {ARGO_LINT_TIMEOUT_SECONDS}s"
    )


def test_a_symlinked_manifest_in_the_destination_is_refused(tmp_path, capsys):
    """The gate cannot promise bytes it does not control.

    A symlink is carried into the lint by its target's bytes, while the output
    keeps the link. Whoever owns the target can replace it after the verdict, so
    what gets applied is not what passed. The gate fails closed everywhere else;
    it has to here too.
    """
    out = tmp_path / "out"
    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", VALID_PLAN, "--output-dir", str(out),
        "--policy-engine", "baseline",
    ]))
    capsys.readouterr()
    target = tmp_path / "elsewhere.yaml"
    target.write_text((next(out.glob("*.yaml"))).read_text(encoding="utf-8"), encoding="utf-8")
    link = out / "linked.yaml"
    link.symlink_to(target)

    with pytest.raises(SystemExit) as exit_info:
        cmd_render_argo(build_parser().parse_args([
            "render-argo", "--input", VALID_PLAN, "--output-dir", str(out),
            "--argo-lint", "--argo-bin", str(_fake_argo(tmp_path, 0)),
            "--policy-engine", "baseline",
        ]))
    report = json.loads(capsys.readouterr().out)

    assert exit_info.value.code == 2, report
    assert report["status"] == "error", report
    assert report.get("reason") == "symlinked-manifest", report
    assert link.is_symlink(), "the destination was modified by a refused render"


def test_a_cleanup_failure_after_a_passing_lint_stays_structured(tmp_path, capsys, monkeypatch):
    """Three outcomes a caller has to be able to tell apart.

    The linter rejected. The linter could not reach a verdict. The linter passed
    and something after it failed with the output untouched. Cleanup of the
    carried copies runs after the verdict and outside the structured path, so an
    unlink that fails there reports the third as a traceback.
    """
    out = tmp_path / "out"
    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", VALID_PLAN, "--output-dir", str(out),
        "--policy-engine", "baseline",
    ]))
    capsys.readouterr()
    # Carried, not staged: the gate only copies an existing manifest whose name
    # this render does not itself produce, so a same-named file exercises nothing.
    produced = next(out.glob("*.yaml"))
    (out / "kept-under-another-name.yaml").write_text(
        produced.read_text(encoding="utf-8"), encoding="utf-8"
    )
    before = {p.name: p.read_text(encoding="utf-8") for p in out.glob("*.yaml")}

    real_unlink = Path.unlink

    def refuse(self, *a, **k):
        if ".argo-lint-staging-" in str(self):
            raise OSError(13, "Permission denied")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", refuse)

    with pytest.raises(SystemExit) as exit_info:
        cmd_render_argo(build_parser().parse_args([
            "render-argo", "--input", VALID_PLAN, "--output-dir", str(out),
            "--argo-lint", "--argo-bin", str(_fake_argo(tmp_path, 0)),
            "--policy-engine", "baseline",
        ]))
    report = json.loads(capsys.readouterr().out)

    assert exit_info.value.code == 2, report
    assert report["status"] == "error", report
    assert report["lint"] == "passed", report
    assert report.get("reason") == "staging-cleanup-failed", report
    assert {p.name: p.read_text(encoding="utf-8") for p in out.glob("*.yaml")} == before


def test_a_cleanup_failure_does_not_erase_a_lint_rejection(tmp_path, capsys, monkeypatch):
    """A rejection is a verdict, and a failed cleanup does not unmake it.

    Exit 1 says the linter rejected something and exit 2 says it never answered.
    Reporting the rejection in the body while exiting 2 tells the caller both, and
    the one that matters is the one CI reads.
    """
    out = tmp_path / "out"
    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", VALID_PLAN, "--output-dir", str(out),
        "--policy-engine", "baseline",
    ]))
    capsys.readouterr()
    produced = next(out.glob("*.yaml"))
    (out / "kept-under-another-name.yaml").write_text(
        produced.read_text(encoding="utf-8"), encoding="utf-8"
    )

    real_unlink = Path.unlink

    def refuse(self, *a, **k):
        if ".argo-lint-staging-" in str(self):
            raise OSError(13, "Permission denied")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", refuse)

    with pytest.raises(SystemExit) as exit_info:
        cmd_render_argo(build_parser().parse_args([
            "render-argo", "--input", VALID_PLAN, "--output-dir", str(out),
            "--argo-lint", "--argo-bin", str(_fake_argo(tmp_path, 1)),
            "--policy-engine", "baseline",
        ]))
    report = json.loads(capsys.readouterr().out)

    assert exit_info.value.code == 1, report
    assert report["lint"] == "failed", report
    assert report.get("reason") == "staging-cleanup-failed", report
