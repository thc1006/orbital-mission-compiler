from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import yaml

from .compiler import (
    ArgoLintUnavailable,
    DEFAULT_POLICY_BUNDLE,
    DEFAULT_POLICY_DECISION,
    PolicyEngineUnavailableError,
    PolicyViolationError,
    compile_file,
    enforce_policy_or_raise,
    load_mission_plan,
    compile_plan_to_intents,
    render_kueue_job,
    render_resource_claim_templates,
    DRA_ROUTE_LABEL,
    kueue_step_projection,
    atomic_write,
    preflight_unique,
    preflight_writable,
    resolve_argo_bin,
    argo_lint_path,
    stale_rendered_artifacts,
    render_workload_priority_classes,
    typed_violations_from_decision,
    write_individual_workflows,
    sanitize_k8s_name,
    ORCHIDE_PRIORITY_CLASS_PREFIX,
)
from .policy import eval_policy

_UNSAFE_SKIP_POLICY_HELP = (
    "DEV ONLY. Skip the policy admission gate and emit artifacts even for a plan the "
    "policy layer would deny. By DEFAULT the compiler is fail-closed: it runs the policy "
    "layer before rendering and produces no artifact for a denied plan. Bypassing the "
    "gate forfeits the pre-uplink guarantee."
)
_POLICY_ENGINE_HELP = (
    "Which policy engine enforces the gate. 'opa' (default) executes the versioned, "
    "independently-auditable Rego bundle -- the authoritative policy-as-code path an "
    "external reviewer runs; it fails closed if opa is unavailable. 'baseline' uses the "
    "proven-equivalent in-process mirror (no opa subprocess), for offline use."
)


_PRUNE_HELP = (
    "Delete artifacts in the output directory that an earlier render of this tool "
    "wrote and this one did not replace. Without it they are reported under "
    "'stale' and left in place: a render writes what the plan describes, it does "
    "not empty the directory, so after a plan shrinks, deploying the directory "
    "would redeploy the workloads the plan no longer asks for. Only files carrying "
    "this tool's own labels are considered."
)

# The Kueue Job carries generateName and no name, which is what lets one rendered
# file be submitted repeatedly as distinct Jobs. kubectl apply needs a name, so
# `apply -f` over this output cannot create the Job.
#
# It does not stop there either. kubectl's apply builder runs with
# ContinueOnError, so it applies every OTHER document -- the ones before the Job
# and the ones after it, including the four cluster-scoped priority classes -- and
# reports the failure at the end with exit 1. Verified with --dry-run=server: two
# named ConfigMaps applied, the generateName one refused, exit 1. So the outcome
# is not "a partial deployment up to the failure": it is the whole set except the
# Job, which is the one document that carries the workload.
#
# `kubectl create -f` takes all of it. Repeat deployments are the awkward case,
# because create is not idempotent for the named documents: apply those and create
# the Job, which is what scripts/validate_live_cluster.sh does.
_KUEUE_DEPLOY_NOTE = (
    "Deploy this output with 'kubectl create -f <dir>': the Job uses generateName, "
    "so 'kubectl apply' cannot create it -- and applies everything else anyway, "
    "leaving the priority classes and claim templates on the cluster without the "
    "workload. To redeploy, apply the named documents (listed under 'apply') and "
    "create the Job (listed under 'create'), since create is not idempotent."
)


def _report_stale(result: dict[str, object], output_dir: str, written: list[Path], prune: bool) -> None:
    stale = stale_rendered_artifacts(output_dir, written)
    if not stale:
        return
    if prune:
        for path in stale:
            path.unlink()
        result["pruned"] = [str(p) for p in stale]
        return
    result["stale"] = [str(p) for p in stale]
    print(
        f"warning: {len(stale)} artifact(s) in {output_dir} are left over from an "
        f"earlier render and were not replaced; applying the directory would "
        f"redeploy them. Re-run with --prune to remove them.",
        file=sys.stderr,
    )


def _add_policy_args(p: argparse.ArgumentParser) -> None:
    """Add the shared policy-gate flags to an artifact-producing subcommand."""
    p.add_argument("--unsafe-skip-policy", action="store_true", help=_UNSAFE_SKIP_POLICY_HELP)
    p.add_argument(
        "--policy-engine", choices=("opa", "baseline"), default="opa", help=_POLICY_ENGINE_HELP
    )
    p.add_argument("--bundle", default=DEFAULT_POLICY_BUNDLE, help="OPA policy bundle directory")
    p.add_argument("--decision", default=DEFAULT_POLICY_DECISION, help="OPA decision path")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orbital-mission-compiler")
    sub = parser.add_subparsers(dest="command", required=True)

    compile_p = sub.add_parser("compile", help="Compile mission plan to workflow payload")
    compile_p.add_argument("--input", required=True)
    compile_p.add_argument("--output", required=True)
    _add_policy_args(compile_p)
    compile_p.set_defaults(func=cmd_compile)

    render_p = sub.add_parser("render-argo", help="Render individual Argo Workflow manifests")
    render_p.add_argument("--input", required=True)
    render_p.add_argument("--output-dir", required=True)
    render_p.add_argument(
        "--dra-fallback",
        action="store_true",
        help="Wire the accelerator-fallback step's Pod to a DRA firstAvailable "
        "ResourceClaimTemplate via podSpecPatch (scheduler-level GPU->CPU fallback), "
        "and emit that RCT alongside the Workflow as a self-contained multi-doc file. "
        "Off by default (runtime env-var switch). The firstAvailable claim is a "
        "scheduler-route artifact and is not Kueue quota-counted.",
    )
    render_p.add_argument("--prune", action="store_true", help=_PRUNE_HELP)
    render_p.add_argument(
        "--namespace",
        default=None,
        help="Stamp metadata.namespace on the rendered objects. Off by default, so "
        "an ordinary Workflow stays namespace-less and the namespace is chosen at "
        "'argo submit -n' or 'kubectl apply -n' time. --dra-fallback needs one, "
        "because the Workflow and the claim template it references must agree, and "
        "defaults to 'orbital-demo' there.",
    )
    render_p.add_argument(
        "--argo-lint",
        action="store_true",
        help="After rendering, run the official 'argo lint' as a fail-closed gate. "
        "Manifests are staged and published only if lint passes, so a rejected "
        "render leaves the output directory unchanged. A lint failure exits 1; "
        "the gate being unable to run at all -- CLI absent, timeout, no manifest "
        "to lint -- exits 2. Off by default, so the CLI stays optional locally.",
    )
    render_p.add_argument(
        "--argo-bin",
        default="argo",
        help="Argo CLI executable used by --argo-lint (name on PATH or a path). "
        "Its version sets the lint semantics applied.",
    )
    render_p.add_argument(
        "--service-account",
        default=None,
        help="Stamp spec.serviceAccountName on the rendered Workflow. Needed when "
        "the multi-doc --dra-fallback bundle is applied with kubectl, since "
        "'argo submit --serviceaccount' cannot be used on it (argo submit drops "
        "the ResourceClaimTemplate document).",
    )
    _add_policy_args(render_p)
    render_p.set_defaults(func=cmd_render_argo)

    inspect_p = sub.add_parser("inspect", help="Inspect compiled workflow intents")
    inspect_p.add_argument("--input", required=True)
    inspect_p.set_defaults(func=cmd_inspect)

    kueue_p = sub.add_parser("render-kueue", help="Render Kueue-compatible Job manifests")
    kueue_p.add_argument("--input", required=True)
    kueue_p.add_argument("--output-dir", required=True)
    kueue_p.add_argument("--prune", action="store_true", help=_PRUNE_HELP)
    kueue_p.add_argument("--queue", default="orbital-demo-local")
    kueue_p.add_argument("--namespace", default="orbital-demo")
    kueue_p.add_argument(
        "--dra-fallback",
        action="store_true",
        help="Additionally emit the scheduler-route DRA firstAvailable claim "
        "(accelerator->CPU) for steps that declare a driver-backed "
        "fallback_resource_class. The Job itself still references the 'exactly' "
        "GPU claim, because Kueue rejects a firstAvailable request as "
        "inadmissible and quota-counts only 'exactly'. The firstAvailable "
        "template is therefore for a non-Kueue consumer; 'render-argo "
        "--dra-fallback' emits it wired to a Workflow that uses it.",
    )
    kueue_p.add_argument(
        "--priority-class",
        action="store_true",
        help="Label each Job with kueue.x-k8s.io/priority-class (mission priority -> "
        "ORCHIDE tier -> WorkloadPriorityClass), so priority feeds Kueue queue sorting "
        "and preemption eligibility. The referenced classes must exist -- pair with "
        "--emit-priority-classes and apply them first.",
    )
    kueue_p.add_argument(
        "--emit-priority-classes",
        action="store_true",
        help="Also write the four cluster-scoped WorkloadPriorityClass objects (one per "
        "ORCHIDE tier) to workload-priority-classes.yaml in the output dir.",
    )
    kueue_p.add_argument(
        "--priority-class-prefix",
        default=ORCHIDE_PRIORITY_CLASS_PREFIX,
        help="Name prefix for the WorkloadPriorityClass objects and the Job label "
        f"(default {ORCHIDE_PRIORITY_CLASS_PREFIX!r}); set per-installation to avoid "
        "collisions on the cluster-scoped names.",
    )
    _add_policy_args(kueue_p)
    kueue_p.set_defaults(func=cmd_render_kueue)

    policy_p = sub.add_parser("policy", help="Evaluate policy pack with OPA if available")
    policy_p.add_argument("--input", required=True)
    policy_p.add_argument("--bundle", default=DEFAULT_POLICY_BUNDLE)
    policy_p.add_argument("--decision", default=DEFAULT_POLICY_DECISION)
    policy_p.set_defaults(func=cmd_policy)

    return parser


def cmd_compile(args: argparse.Namespace) -> None:
    payload = compile_file(
        args.input, args.output, enforce_policy=not args.unsafe_skip_policy,
        policy_engine=args.policy_engine, bundle=args.bundle, decision=args.decision,
    )
    print(json.dumps({"status": "ok", "workflows": len(payload["workflows"])}, indent=2))


def _render_argo(args: argparse.Namespace, output_dir: str | Path) -> list[Path]:
    # args.namespace goes straight through: the writer supplies one for a DRA
    # bundle, whose two documents have to share it, and leaves an ordinary render
    # namespace-less so it is chosen when the manifest is applied.
    return write_individual_workflows(
        args.input, output_dir, enforce_policy=not args.unsafe_skip_policy,
        policy_engine=args.policy_engine, bundle=args.bundle, decision=args.decision,
        dra_fallback=args.dra_fallback, namespace=args.namespace,
        service_account=args.service_account,
    )


def cmd_render_argo(args: argparse.Namespace) -> None:
    if args.argo_lint:
        _render_argo_with_lint_gate(args)
        return
    written = _render_argo(args, args.output_dir)
    result: dict[str, object] = {"status": "ok", "files": [str(p) for p in written]}
    _report_stale(result, args.output_dir, written, args.prune)
    print(json.dumps(result, indent=2))


def _nearest_existing_ancestor(path: Path) -> Path:
    """The closest existing directory at or above ``path``.

    Staging goes here so publishing is a same-filesystem rename, without having
    to create the output directory first: a denied plan or a rejected lint must
    leave a path that did not exist before the command exactly as absent. When
    the output directory does exist this is the directory itself, which is
    deliberate -- an output directory that is a mount point has a parent on a
    different filesystem, and a rename across that boundary cannot work.
    """
    current = path.absolute()
    while not current.is_dir():
        parent = current.parent
        if parent == current:
            break
        current = parent
    return current


@contextlib.contextmanager
def _publish_lock(out_dir: Path) -> Iterator[None]:
    """Serialise publishing into one output directory.

    Two renders publishing at once interleave their files and the directory ends
    up holding some of each, with nothing recording that. The lock lives beside
    the output rather than inside it, so taking it does not create the directory
    a failed run has to leave absent.
    """
    # Keyed by the output path but kept in the system temp directory, for two
    # reasons. It has to be somewhere that exists whether or not the output
    # directory does -- anchoring it to the nearest existing ancestor would give
    # two processes different lock files when one of them runs before the
    # directory is created and the other after, which is exactly when they would
    # collide. And a lock file is not something to leave in an operator's output.
    digest = hashlib.sha256(str(out_dir.absolute()).encode("utf-8")).hexdigest()[:16]
    lock_path = Path(tempfile.gettempdir()) / f"orbital-publish-{digest}.lock"
    handle = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)


def _publish(staged: list[Path], out_dir: Path) -> list[Path]:
    """Move a rendered set into the output directory, all of it or none of it.

    Each rename is atomic on its own, but the set is what a caller applies. A
    failure part-way through would leave the directory holding some files from
    this render and some from the last one, and nothing would say so. Whatever a
    rename displaces is kept aside until the whole set lands, and put back if it
    does not; directories this call created are removed again on the way out.
    """
    created_dirs: list[Path] = []
    probe = out_dir.absolute()
    while not probe.is_dir():
        created_dirs.append(probe)
        probe = probe.parent
    backup_dir = Path(tempfile.mkdtemp(prefix=".orbital-publish-backup-", dir=probe))
    out_dir.mkdir(parents=True, exist_ok=True)

    displaced: dict[Path, Path] = {}
    published: list[Path] = []
    try:
        for path in staged:
            target = out_dir / path.name
            if target.exists():
                kept = backup_dir / target.name
                os.replace(target, kept)
                displaced[target] = kept
            os.replace(path, target)
            published.append(target)
    except OSError:
        for target in published:
            with contextlib.suppress(OSError):
                target.unlink()
        for target, kept in displaced.items():
            with contextlib.suppress(OSError):
                os.replace(kept, target)
        for created in created_dirs:
            with contextlib.suppress(OSError):
                created.rmdir()
        raise
    finally:
        shutil.rmtree(backup_dir, ignore_errors=True)
    return published


def _render_argo_with_lint_gate(args: argparse.Namespace) -> None:
    """Render, lint, and publish only if the linter accepts the whole set.

    Order matters. Rendering comes first, so a schema or policy failure is
    reported as itself instead of being masked by a missing linter. The CLI is
    resolved before the empty-render check, because a plan is allowed to render
    nothing -- a download-only plan is schema-valid and passes the policy layer --
    and an empty render must not be able to report a lint that never ran.
    """
    out_dir = Path(args.output_dir)
    staging = Path(tempfile.mkdtemp(
        prefix=".argo-lint-staging-", dir=_nearest_existing_ancestor(out_dir)
    ))
    carried: list[Path] = []
    try:
        written = _render_argo(args, staging)

        try:
            resolved = resolve_argo_bin(args.argo_bin)
        except ArgoLintUnavailable as exc:
            print(json.dumps({"status": "error", "lint": "unavailable", "message": str(exc)}, indent=2))
            raise SystemExit(2) from exc

        if not written:
            print(json.dumps({
                "status": "error", "lint": "not-run", "reason": "no-manifests",
                "message": "the plan rendered no Argo Workflow, so nothing was linted",
            }, indent=2))
            raise SystemExit(2)

        # Lint what the directory will actually hold. Staging carries only this
        # render, but a file already in the output that this plan no longer
        # produces survives the publish, and `kubectl apply -f <dir>` takes it
        # along. Copying those in makes the verdict cover the set a caller
        # applies; the copies are dropped again before publishing, so this does
        # not rewrite files the render does not own.
        staged_names = {path.name for path in written}
        if out_dir.is_dir():
            for existing in sorted(out_dir.glob("*.yaml")):
                if existing.name in staged_names or not existing.is_file():
                    continue
                copy = staging / existing.name
                shutil.copy2(existing, copy)
                carried.append(copy)

        rc, output = argo_lint_path(staging, argo_bin=args.argo_bin, resolved=resolved)
        for copy in carried:
            copy.unlink()
        carried = []
        if rc != 0:
            print(json.dumps({
                "status": "lint-failed", "files": [],
                "lint_output": output.strip(),
                "message": f"argo lint rejected the manifests this render would leave in "
                           f"{out_dir}; it was left unchanged",
            }, indent=2))
            raise SystemExit(1)

        try:
            with _publish_lock(out_dir):
                published = _publish(written, out_dir)
        except OSError as exc:
            print(json.dumps({
                "status": "error", "lint": "passed", "reason": "publish-failed",
                "message": f"the manifests passed lint but could not be published to "
                           f"{out_dir}, which was rolled back to its previous contents: {exc}",
            }, indent=2))
            raise SystemExit(2) from exc
    except ArgoLintUnavailable as exc:
        print(json.dumps({"status": "error", "lint": "unavailable", "message": str(exc)}, indent=2))
        raise SystemExit(2) from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    result: dict[str, object] = {
        "status": "ok", "files": [str(p) for p in published], "lint": "passed",
        "lint_output": output.strip(),
    }
    if staging.exists():
        # Reported rather than swallowed: the render succeeded, but a staging
        # directory left inside the operator's output is theirs to clean up and
        # they can only do that if they are told.
        result["staging_left_behind"] = str(staging)
        print(f"warning: could not remove the staging directory {staging}", file=sys.stderr)
    # Leftovers are reported against the published set, so the staging round trip
    # does not make every previous artifact look stale. They were part of the lint
    # above, so this is about what to apply, not about whether it is valid.
    _report_stale(result, args.output_dir, published, args.prune)
    print(json.dumps(result, indent=2))


def cmd_inspect(args: argparse.Namespace) -> None:
    plan = load_mission_plan(args.input)
    intents = compile_plan_to_intents(plan)
    data = [i.model_dump(mode="json") for i in intents]
    print(json.dumps(data, indent=2))


def cmd_render_kueue(args: argparse.Namespace) -> None:
    plan = load_mission_plan(args.input)
    if not args.unsafe_skip_policy:
        enforce_policy_or_raise(
            plan, engine=args.policy_engine, bundle=args.bundle, decision=args.decision
        )
    intents = compile_plan_to_intents(plan)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Render everything first, then write: writing as we go leaves a partial set
    # behind when a later intent fails, and a consumer cannot tell that apart
    # from a complete render.
    planned: list[tuple[Path, str]] = []
    projections: list[dict[str, object]] = []
    dropped_total = 0
    if args.emit_priority_classes:
        wpc = render_workload_priority_classes(prefix=args.priority_class_prefix)
        planned.append(
            (out_dir / "workload-priority-classes.yaml", yaml.safe_dump_all(wpc, sort_keys=False))
        )
    for intent in intents:
        templates = render_resource_claim_templates(
            intent, namespace=args.namespace, dra_fallback=args.dra_fallback
        )
        job = render_kueue_job(
            intent,
            queue_name=args.queue,
            namespace=args.namespace,
            dra_fallback=args.dra_fallback,
            priority_class=args.priority_class,
            priority_class_prefix=args.priority_class_prefix,
        )
        # From the renderer, which selected the step, rather than recomputed by
        # name here: two steps may share a name, and this would then report
        # nothing dropped while one of them is silently absent from the Job.
        projection = kueue_step_projection(intent)
        if projection is not None:
            dropped_total += len(projection["steps_not_in_job"])
            projections.append(projection)
        safe_name = sanitize_k8s_name(intent.workflow_name)
        # Kueue admission rejects a firstAvailable claim, so the Job is admitted on
        # the exactly claim and never references the firstAvailable one. Keeping
        # both in a single file invites the reading that the admitted Job falls
        # back, and applying that file creates a claim template nothing consumes.
        # The scheduler-route claim goes to its own file, for a plain Pod or an
        # Argo render to reference.
        scheduler_route = [
            t for t in templates
            if t["metadata"].get("labels", {}).get(DRA_ROUTE_LABEL) == "scheduler"
        ]
        kueue_route = [t for t in templates if t not in scheduler_route]
        planned.append((
            out_dir / f"{safe_name}-kueue.yaml",
            yaml.safe_dump_all(kueue_route + [job], sort_keys=False),
        ))
        if scheduler_route:
            planned.append((
                out_dir / f"{safe_name}-scheduler-fallback.yaml",
                yaml.safe_dump_all(scheduler_route, sort_keys=False),
            ))

    preflight_unique([path for path, _ in planned])
    preflight_writable(planned)
    written = []
    for out, text in planned:
        atomic_write(out, text)
        written.append(out)
    result: dict[str, object] = {"status": "ok", "files": [str(p) for p in written]}
    # Which verb each file takes, so a caller does not have to open them to find
    # out. A file holding any document without metadata.name cannot be applied.
    apply_files: list[str] = []
    create_files: list[str] = []
    for path, text in planned:
        docs = [d for d in yaml.safe_load_all(text) if d]
        # `all()` over no documents is True, which would put a file holding nothing
        # in the group whose meaning is "every document here has a name". kubectl
        # answers `error: no objects passed to apply` for such a directory, so the
        # vacuous case belongs on the other side. A document that is not a mapping
        # has no metadata to ask about and is not applyable either.
        named = bool(docs) and all(
            isinstance(d, dict) and (d.get("metadata") or {}).get("name") for d in docs
        )
        (apply_files if named else create_files).append(str(path))
    result["apply"] = apply_files
    result["create"] = create_files
    result["deploy"] = _KUEUE_DEPLOY_NOTE
    if projections:
        # Not "ok". A caller keying on status would otherwise treat a one-step
        # admission probe as the whole service, apply it alongside the Argo
        # render, and run that step twice.
        result["status"] = "projected"
        result["complete_service"] = False
        # A Kueue Job runs one container, so a multi-step service is admitted as
        # its primary step. Reporting it here keeps "the render succeeded" from
        # reading as "the service was rendered whole".
        result["step_projection"] = projections
        print(
            f"warning: the Kueue Job is a standalone workload that runs one container, so "
            f"{dropped_total} step(s) across {len(projections)} service(s) are not in it. It "
            f"demonstrates Kueue admission for the primary step; it does not admit or gate the "
            f"Argo Workflow, which is what runs the full sequence -- applying both artifacts "
            f"runs that step twice. See 'step_projection'.",
            file=sys.stderr,
        )
    _report_stale(result, args.output_dir, written, args.prune)
    print(json.dumps(result))


def cmd_policy(args: argparse.Namespace) -> None:
    """Evaluate the OPA policy and gate on its DECISION, not just whether OPA ran.

    OPA's ``eval`` returns exit 0 whenever evaluation *succeeds*, even when the
    plan is denied (``allow: false`` / non-empty ``deny``). This command parses the
    decision and exits non-zero on denial, so it is a usable admission gate in CI
    and scripts -- not merely a "did OPA run" smoke.
    """
    plan = load_mission_plan(args.input)
    payload = plan.model_dump(mode="json")
    rc, out = eval_policy(args.bundle, payload, args.decision)
    print(out)
    # OPA unavailable (rc=2) or evaluation error (rc=1): cannot render a decision.
    if rc != 0:
        raise SystemExit(rc)
    try:
        value = json.loads(out)["result"][0]["expressions"][0]["value"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        # An undefined or unparseable result is not an allow: this command is the
        # standalone gate, so it must not report success for a decision it could
        # not read. Exit 2 keeps "no usable decision" distinct from "denied" (1).
        print(
            json.dumps({"status": "error", "reason": "undecidable", "error": str(exc)}),
            file=sys.stderr,
        )
        raise SystemExit(2)
    try:
        # Same strict parser the artifact gate uses, so the standalone command
        # cannot admit a plan the compile/render path would reject.
        typed = typed_violations_from_decision(value)
    except PolicyEngineUnavailableError as exc:
        print(
            json.dumps({"status": "error", "reason": "policy_engine_unavailable", "error": str(exc)}),
            file=sys.stderr,
        )
        raise SystemExit(2)
    if typed:
        # Report the typed violations the policy already computed (rule_id,
        # severity tier, provenance, JSON-Pointer path), not the plain-string
        # deny projection, so CI and other consumers can act on the category
        # rather than parse the message.
        print(
            json.dumps({"status": "denied", "violations": typed}),
            file=sys.stderr,
        )
        raise SystemExit(1)
    raise SystemExit(0)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except PolicyViolationError as exc:
        # Fail closed: a denied plan produces no artifact and a non-zero exit.
        # Emit the TYPED violations (rule/severity/provenance/path/message) so a
        # consumer can triage without re-parsing prose.
        print(
            json.dumps(
                {
                    "status": "denied",
                    "error": str(exc),
                    "violations": exc.violations,
                    "messages": exc.messages,
                    "hint": "re-run with --unsafe-skip-policy to bypass the gate (dev only)",
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    except PolicyEngineUnavailableError as exc:
        # Fail closed on an engine that cannot render a decision (never silently
        # downgrade or skip). Distinct exit code from a policy denial.
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": "policy_engine_unavailable",
                    "error": str(exc),
                    "hint": "install opa, or pass --policy-engine=baseline (dev only)",
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
